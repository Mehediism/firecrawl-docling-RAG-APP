import os
import re
import time
import hashlib
from datetime import datetime
from langchain_community.document_loaders.firecrawl import FireCrawlLoader
from langchain_docling.loader import DoclingLoader
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from shared.embeddings import get_embeddings_model, count_tokens
from shared.sql_client import get_pg_session
from shared.logger import logger
from ingestion.models import Source, Page, Embedding

INPUT_TOKEN_THRESHOLD = 1900
CHUNK_CHAR_TARGET = 1800
CHUNK_CHAR_OVERLAP = 200


def calculate_hash(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def _structure_aware_split(markdown_text: str, page_title: str) -> list[str]:
    """Split markdown by headings, prepending heading context to each chunk.

    Falls back to plain recursive split when the document has no markdown
    headings. Each chunk carries an explicit `[Title:]` / `[Section:]` header
    so the embedder and the LLM both see what the chunk is *about*, which
    massively improves retrieval and grounding for legal/structured docs.
    """
    headers = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers,
        strip_headers=False,
    )

    try:
        sections = md_splitter.split_text(markdown_text)
    except Exception:
        sections = []

    if not sections:
        recursive = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_CHAR_TARGET,
            chunk_overlap=CHUNK_CHAR_OVERLAP,
        )
        raw = recursive.split_text(markdown_text)
        prefix = f"[Title: {page_title}]\n" if page_title else ""
        return [prefix + chunk for chunk in raw]

    recursive = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_CHAR_TARGET,
        chunk_overlap=CHUNK_CHAR_OVERLAP,
    )

    final_chunks: list[str] = []
    for section in sections:
        meta = section.metadata or {}
        section_path = " > ".join(
            v.strip() for v in (meta.get("h1"), meta.get("h2"), meta.get("h3"), meta.get("h4")) if v
        )
        header_lines = []
        if page_title:
            header_lines.append(f"[Title: {page_title}]")
        if section_path:
            header_lines.append(f"[Section: {section_path}]")
        header_block = ("\n".join(header_lines) + "\n") if header_lines else ""

        body = section.page_content.strip()
        if not body:
            continue

        if len(body) <= CHUNK_CHAR_TARGET:
            final_chunks.append(header_block + body)
            continue

        for piece in recursive.split_text(body):
            final_chunks.append(header_block + piece)

    return final_chunks


def chunk_text(text: str, token_count: int, page_title: str = "") -> list[str]:
    """Backwards-compatible chunker. Uses structure-aware split for markdown."""
    if token_count < INPUT_TOKEN_THRESHOLD and "\n#" not in text and "\n##" not in text:
        prefix = f"[Title: {page_title}]\n" if page_title else ""
        return [prefix + text]
    return _structure_aware_split(text, page_title)


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

            CRAWL_PAGE_LIMIT = int(os.getenv("FIRECRAWL_PAGE_LIMIT", "20000"))
            CRAWL_MAX_DEPTH = int(os.getenv("FIRECRAWL_MAX_DEPTH", "15"))

            crawl_params = {
                "limit": CRAWL_PAGE_LIMIT,
                "maxDepth": CRAWL_MAX_DEPTH,
                "allowBackwardLinks": True,
                "scrapeOptions": {
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
            }

            if firecrawl_api_url:
                logger.info(
                    f"Using LOCAL self-hosted Firecrawl at: {firecrawl_api_url} "
                    f"(limit: {CRAWL_PAGE_LIMIT} pages, maxDepth: {CRAWL_MAX_DEPTH})"
                )
                loader = FireCrawlLoader(
                    api_key=firecrawl_api_key or "self-hosted-dummy",
                    url=source.source_name,
                    mode="crawl",
                    api_url=firecrawl_api_url,
                    params=crawl_params,
                )
            else:
                logger.info(
                    f"Using Firecrawl CLOUD API (limit: {CRAWL_PAGE_LIMIT} pages, "
                    f"maxDepth: {CRAWL_MAX_DEPTH})"
                )
                loader = FireCrawlLoader(
                    api_key=firecrawl_api_key,
                    url=source.source_name,
                    mode="crawl",
                    params=crawl_params,
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
            pages_empty = 0
            depth_histogram: dict[int, int] = {}
            t0 = time.time()
            commit_every = 25  # checkpoint progress periodically

            total_docs = len(docs)
            for doc_idx, doc in enumerate(docs, start=1):
                page_url = doc.metadata.get("sourceURL") or doc.metadata.get("url")
                if not page_url:
                    page_url = source.source_name

                page_title = doc.metadata.get("title", "")
                content = doc.page_content

                # Approximate URL depth (path segment count) for crawl observability
                try:
                    url_path = page_url.split("://", 1)[-1].split("/", 1)[1] if "/" in page_url.split("://", 1)[-1] else ""
                    url_depth = len([p for p in url_path.split("/") if p])
                except Exception:
                    url_depth = 0
                depth_histogram[url_depth] = depth_histogram.get(url_depth, 0) + 1

                if not content.strip():
                    pages_empty += 1
                    logger.warning(f"[{doc_idx}/{total_docs}] EMPTY page (skipped): {page_url}")
                    continue

                page_hash = calculate_hash(content)

                existing_page = session.query(Page).filter(
                    Page.source_id == source_id,
                    Page.page_url == page_url
                ).first()

                if existing_page and existing_page.last_hash == page_hash:
                    pages_skipped += 1
                    logger.info(f"[{doc_idx}/{total_docs}] UNCHANGED (skip): {page_url}")
                    continue

                if not existing_page:
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
                    page_action = "NEW"
                else:
                    existing_page.content = content
                    existing_page.last_hash = page_hash
                    existing_page.page_title = page_title
                    existing_page.last_updated = datetime.now()
                    existing_page.status = "processing"
                    session.flush()
                    page_id = existing_page.id
                    session.query(Embedding).filter(Embedding.page_id == page_id).delete()
                    page_action = "UPDATED"

                token_count = count_tokens(content)
                chunks = chunk_text(content, token_count, page_title=page_title)
                logger.info(
                    f"[{doc_idx}/{total_docs}] {page_action} depth={url_depth} "
                    f"tokens={token_count} chunks={len(chunks)} :: {page_url}"
                )

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
                            "chunk_index": i,
                            "url_depth": url_depth,
                        }
                    )
                    session.add(new_embedding)
                    total_chunks += 1

                if existing_page:
                    existing_page.status = "processed"
                else:
                    new_page.status = "processed"

                pages_processed += 1

                if pages_processed % commit_every == 0:
                    session.commit()
                    elapsed = time.time() - t0
                    rate = pages_processed / max(elapsed, 1e-3)
                    logger.info(
                        f"... checkpoint: {pages_processed} processed, "
                        f"{total_chunks} chunks, {rate:.1f} pages/s"
                    )

            source.status = "processed"
            source.last_updated = datetime.now()
            session.commit()

            elapsed = time.time() - t0
            depth_summary = ", ".join(f"d{k}={v}" for k, v in sorted(depth_histogram.items()))
            logger.success(
                f"Ingestion complete in {elapsed:.1f}s: "
                f"{pages_processed} processed, {pages_skipped} unchanged, "
                f"{pages_empty} empty, {total_chunks} chunks. "
                f"Depth distribution: {depth_summary}"
            )
            
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

            chunks = chunk_text(full_text, token_count, page_title=source.source_name)
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
