from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class URLRequest(BaseModel):
    url: str


class DocumentUploadResponse(BaseModel):
    message: str
    id: int


class PageResponse(BaseModel):
    id: int
    page_url: str
    page_title: Optional[str] = None
    status: str
    last_updated: Optional[datetime] = None

    class Config:
        from_attributes = True


class PageDetailResponse(PageResponse):
    content: str


class PaginatedPageResponse(BaseModel):
    total: int
    items: List[PageResponse]


class SourceResponse(BaseModel):
    id: int
    source_name: str
    type: str
    status: str
    error: Optional[str] = None
    last_updated: Optional[datetime] = None
    page_count: int = 0

    class Config:
        from_attributes = True


class PaginatedSourceResponse(BaseModel):
    total: int
    items: List[SourceResponse]
