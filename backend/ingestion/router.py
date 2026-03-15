import os
import uuid
from fastapi import APIRouter, BackgroundTasks, Query, HTTPException, UploadFile, File
from ingestion.schema import (
    URLRequest,
    PaginatedSourceResponse,
    SourceResponse,
    DocumentUploadResponse,
    PageResponse,
    PageDetailResponse,
    PaginatedPageResponse,
)
from shared.sql_client import get_pg_session
from ingestion.ingestion import ingest_url_task, ingest_document_task, delete_source
from ingestion.models import Source, Page, Embedding
from shared.logger import logger


ingestion_router = APIRouter()

# Create uploads directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@ingestion_router.get("/ingestion/list", response_model=PaginatedSourceResponse)
def get_sources(skip: int = Query(0), limit: int = Query(5)):

    with get_pg_session() as session:
        total = session.query(Source).count()
        sources = (
            session.query(Source)
            .order_by(Source.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        # Add page_count to each source
        source_responses = []
        for source in sources:
            page_count = session.query(Page).filter(Page.source_id == source.id).count()
            source_responses.append(SourceResponse(
                id=source.id,
                source_name=source.source_name,
                type=source.type,
                status=source.status,
                error=source.error,
                last_updated=source.last_updated,
                page_count=page_count
            ))
    return PaginatedSourceResponse(total=total, items=source_responses)


@ingestion_router.get("/ingestion/{source_id}", response_model=SourceResponse)
def get_source_detail(source_id: int):
    
    with get_pg_session() as session:
        source = session.query(Source).filter(Source.id == source_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        page_count = session.query(Page).filter(Page.source_id == source.id).count()
        return SourceResponse(
            id=source.id,
            source_name=source.source_name,
            type=source.type,
            status=source.status,
            error=source.error,
            last_updated=source.last_updated,
            page_count=page_count
        )


@ingestion_router.get("/ingestion/{source_id}/pages", response_model=PaginatedPageResponse)
def get_source_pages(source_id: int, skip: int = Query(0), limit: int = Query(50)):
    """Get all pages crawled for a specific source."""
    with get_pg_session() as session:
        source = session.query(Source).filter(Source.id == source_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        total = session.query(Page).filter(Page.source_id == source_id).count()
        pages = (
            session.query(Page)
            .filter(Page.source_id == source_id)
            .order_by(Page.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return PaginatedPageResponse(total=total, items=pages)


@ingestion_router.get("/ingestion/pages/{page_id}", response_model=PageDetailResponse)
def get_page_content(page_id: int):
    """Get a single page with its full content."""
    with get_pg_session() as session:
        page = session.query(Page).filter(Page.id == page_id).first()
        if not page:
            raise HTTPException(status_code=404, detail="Page not found")
        return page


@ingestion_router.post("/ingestion/add", status_code=202)
def add_url_source(request: URLRequest, background_tasks: BackgroundTasks):

    with get_pg_session() as session:
        new_source = Source(
            source_name=request.url,
            type="web_url",
            status="pending"
        )
        session.add(new_source)
        session.commit()
        session.refresh(new_source)
    
    background_tasks.add_task(ingest_url_task, new_source.id)
    logger.info(f"Added URL for Firecrawl crawling: {request.url}")
    return {"message": "URL added for crawling", "id": new_source.id}


@ingestion_router.post("/ingestion/add-document", response_model=DocumentUploadResponse, status_code=202)
async def add_document_source(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):

    allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Allowed: {', '.join(allowed_extensions)}"
        )
    
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    logger.info(f"Saved uploaded file: {file_path}")
    
    with get_pg_session() as session:
        new_source = Source(
            source_name=file.filename,
            type="document",
            status="pending",
            file_path=file_path
        )
        session.add(new_source)
        session.commit()
        session.refresh(new_source)
    
    background_tasks.add_task(ingest_document_task, new_source.id)
    logger.info(f"Added document for Docling parsing: {file.filename}")
    
    return DocumentUploadResponse(
        message="Document uploaded for parsing",
        id=new_source.id
    )


@ingestion_router.put("/ingestion/refresh/{source_id}", status_code=202)
def refresh_source_endpoint(source_id: int, background_tasks: BackgroundTasks):
    """Re-process a source (URL or document)."""
    with get_pg_session() as session:
        source = session.query(Source).filter(Source.id == source_id).first()
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        
        source.status = "pending"
        session.commit()
        
        if source.type == "web_url":
            background_tasks.add_task(ingest_url_task, source.id)
        else:
            background_tasks.add_task(ingest_document_task, source.id)
            
    return {"message": "Refresh started"}


@ingestion_router.delete("/ingestion/delete/{source_id}")
def remove_source(source_id: int):
    """Delete a source and its embeddings."""
    delete_source(source_id)
    return {"message": "Deleted"}


@ingestion_router.delete("/ingestion/delete-all")
def remove_all_sources():
    """Delete all sources and embeddings."""
    with get_pg_session() as session:
        # Get all sources to delete files
        sources = session.query(Source).all()
        for source in sources:
            if source.file_path and os.path.exists(source.file_path):
                os.remove(source.file_path)
        
        session.query(Embedding).delete()
        session.query(Page).delete()
        session.query(Source).delete()
        session.commit()
    return {"message": "All sources deleted"}
