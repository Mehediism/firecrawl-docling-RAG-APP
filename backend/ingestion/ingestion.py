import os
import hashlib
from datetime import datetime
from langchain_community.document_loaders.firecrawl import FireCrawlLoader
from langchain_docling.loader import DoclingLoader
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from langchain_text_splitters import RecursiveCharacterTextSplitter
from shared.embeddings import get_embeddings_model, count_tokens
from shared.sql_client import get_pg_session
from shared.logger import logger
from ingestion.models import Source, Page, Embedding

INPUT_TOKEN_THRESHOLD = 1900


def calculate_hash(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def chunk_text(text: str, token_count: int) -> list[str]:
    if token_count < INPUT_TOKEN_THRESHOLD:
        return [text]
    
    num_chunks = (token_count // INPUT_TOKEN_THRESHOLD) + 1
    chars_per_chunk = len(text) // num_chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chars_per_chunk,
        chunk_overlap=200
    )
    return text_splitter.split_text(text)


def ingest_url_task(source_id: int):
    with get_pg_session() as session:
        try:
            source = session.query(Source).filter(Source.id == source_id).first()
            if not source:
                return
        
            source.status = "processing"
            session.commit()
            
            logger.info(f"Starting Firecrawl crawl for: {source.source_name}")
            
            firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
            firecrawl_api_url = os.getenv("FIRECRAWL_API_URL")
            
            CRAWL_PAGE_LIMIT = 10
            
            if firecrawl_api_url:
                logger.info(f"Using LOCAL self-hosted Firecrawl at: {firecrawl_api_url} (limit: {CRAWL_PAGE_LIMIT} pages)")
                loader = FireCrawlLoader(
                    api_key=firecrawl_api_key or "self-hosted-dummy",
                    url=source.source_name,
                    mode="crawl",
                    api_url=firecrawl_api_url,
                    params={"limit": CRAWL_PAGE_LIMIT}
                )
            else:
                logger.info(f"Using Firecrawl CLOUD API (https://api.firecrawl.dev) (limit: {CRAWL_PAGE_LIMIT} pages)")
                loader = FireCrawlLoader(
                    api_key=firecrawl_api_key,
                    url=source.source_name,
                    mode="crawl",
                    params={"limit": CRAWL_PAGE_LIMIT}
                )
            
            docs = loader.load()
            
            logger.info(f"Firecrawl returned {len(docs)} pages")
            
            if not docs:
                logger.warning(f"No pages found for URL: {source.source_name}")
                source.status = "empty"
                source.error = "No pages found."
                session.commit()
                return

            
            embeddings_model = get_embeddings_model()
            base_url = source.source_name
            total_chunks = 0
            pages_processed = 0
            pages_skipped = 0
            
            for doc in docs:
                page_url = doc.metadata.get("sourceURL") or doc.metadata.get("url")
                if not page_url:
                    page_url = source.source_name 
                
                page_title = doc.metadata.get("title", "")
                content = doc.page_content
                
                if not content.strip():
                    logger.warning(f"Skipping empty page: {page_url}")
                    continue
                
                page_hash = calculate_hash(content)
                
                existing_page = session.query(Page).filter(
                    Page.source_id == source_id,
                    Page.page_url == page_url
                ).first()
                
                if existing_page and existing_page.last_hash == page_hash:
                    logger.info(f"Page unchanged, skipping: {page_url}")
                    pages_skipped += 1
                    continue

                if not existing_page:
                    logger.info(f"New page found: {page_url}")
                    new_page = Page(
                        source_id=source_id,
                        page_url=page_url,
                        page_title=page_title,
                        content=content,
                        last_hash=page_hash,
                        status="processing",
                        last_updated=datetime.now()
                    )
                    session.add(new_page)
                    session.flush() 
                    page_id = new_page.id
                else:
                    logger.info(f"Page content changed, updating: {page_url}")
                    existing_page.content = content
                    existing_page.last_hash = page_hash
                    existing_page.page_title = page_title
                    existing_page.last_updated = datetime.now()
                    existing_page.status = "processing"
                    session.flush()
                    page_id = existing_page.id
                    
                    session.query(Embedding).filter(Embedding.page_id == page_id).delete()
                
                token_count = count_tokens(content)
                chunks = chunk_text(content, token_count)
                logger.info(f"Page '{page_title or page_url}' has {token_count} tokens, {len(chunks)} chunks")
                
                for i, chunk in enumerate(chunks):
                    vector = embeddings_model.embed_query(chunk)
                    new_embedding = Embedding(
                        source_id=source_id,
                        page_id=page_id,
                        content=chunk,
                        embedding=vector,
                        chunk_index=i,
                        meta_data={
                            "page_url": page_url,
                            "page_title": page_title,
                            "base_url": base_url,
                            "chunk_index": i
                        }
                    )
                    session.add(new_embedding)
                    total_chunks += 1
                
                if existing_page:
                    existing_page.status = "processed"
                else:
                    new_page.status = "processed" 
                
                pages_processed += 1
            
            source.status = "processed"
            source.last_updated = datetime.now()
            session.commit()
            logger.success(f"Ingestion complete: {pages_processed} processed, {pages_skipped} skipped, {total_chunks} chunks created.")
            
        except Exception as e:
            logger.exception(f"Error processing URL: {e}")
            session.rollback()
            source = session.query(Source).filter(Source.id == source_id).first()
            if source:
                source.status = "failed"
                source.error = str(e)[:500]
                session.commit()


def ingest_document_task(source_id: int):
    with get_pg_session() as session:
        try:
            source = session.query(Source).filter(Source.id == source_id).first()
            if not source:
                return
            
            if not source.file_path:
                logger.error(f"No file path for document source: {source.source_name}")
                source.status = "failed"
                source.error = "No file path provided"
                session.commit()
                return
            
            source.status = "processing"
            session.commit()
            
            logger.info(f"Starting Docling parsing for: {source.file_path}")
            
            pipeline_options = PdfPipelineOptions()
            pipeline_options.accelerator_options = AcceleratorOptions(
                num_threads=4, device=AcceleratorDevice.CPU
            )
            
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                    InputFormat.IMAGE: PdfFormatOption(pipeline_options=pipeline_options),
                }
            )
            
            loader = DoclingLoader(file_path=source.file_path, converter=converter)
            docs = loader.load()
            
            logger.info(f"Docling returned {len(docs)} document chunks")
            
            full_text = "\n\n".join([doc.page_content for doc in docs])
            
            if not full_text.strip():
                logger.warning(f"No readable content found in document: {source.source_name}")
                source.status = "empty"
                source.error = "No readable content found in document."
                session.commit()
                return

            new_hash = calculate_hash(full_text)
        
            if source.last_hash == new_hash and source.status == "processed":
                logger.info("Content unchanged, skipping re-processing")
                return

            source.last_hash = new_hash
            session.commit()

            token_count = count_tokens(full_text)
            logger.info(f"Document has {token_count} tokens")
            
            chunks = chunk_text(full_text, token_count)
            logger.info(f"Document chunked into {len(chunks)} parts")
        
            embeddings_model = get_embeddings_model()
            session.query(Embedding).filter(Embedding.source_id == source.id).delete()
        
            for i, chunk in enumerate(chunks):
                vector = embeddings_model.embed_query(chunk)
                new_embedding = Embedding(
                    source_id=source.id,
                    page_id=None,
                    content=chunk,
                    embedding=vector,
                    chunk_index=i,
                    meta_data={
                        "document_name": source.source_name,
                        "chunk_index": i
                    }
                )
                session.add(new_embedding)
        
            source.status = "processed"
            source.last_updated = datetime.now()
            session.commit()
            logger.success(f"Successfully ingested document: {source.source_name}")
            
        except Exception as e:
            logger.exception(f"Error processing document: {e}")
            session.rollback()
            source = session.query(Source).filter(Source.id == source_id).first()
            if source:
                source.status = "failed"
                source.error = str(e)[:500]
                session.commit()


def delete_source(source_id: int):
    try:
        with get_pg_session() as session:
            source = session.query(Source).filter(Source.id == source_id).first()
            if source:
                if source.file_path and os.path.exists(source.file_path):
                    os.remove(source.file_path)
                    logger.info(f"Deleted file: {source.file_path}")
                session.delete(source)
                session.commit()
                logger.info(f"Deleted source: {source_id}")
    except Exception as e:
        logger.exception(f"Error deleting source: {e}")
        raise
