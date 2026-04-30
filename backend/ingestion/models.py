from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from shared.sql_client import Base
from shared.config import EMBEDDING_DIMENSIONS


class Source(Base):
    __tablename__ = "sources"
    
    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String, index=True)
    type = Column(String)
    status = Column(String, default="pending")
    error = Column(Text, nullable=True)
    last_hash = Column(String, nullable=True)
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    file_path = Column(String, nullable=True)
    
    pages = relationship("Page", back_populates="source", cascade="all, delete-orphan")
    embeddings = relationship("Embedding", back_populates="source", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"
    
    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    page_url = Column(String, index=True)
    page_title = Column(String, nullable=True)
    content = Column(Text)
    last_hash = Column(String, nullable=True)
    status = Column(String, default="pending")
    last_updated = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    source = relationship("Source", back_populates="pages")
    embeddings = relationship("Embedding", back_populates="page", cascade="all, delete-orphan")


class Embedding(Base):
    __tablename__ = "embeddings"
    
    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    page_id = Column(Integer, ForeignKey("pages.id", ondelete="CASCADE"), nullable=True, index=True)
    
    content = Column(Text)
    embedding = Column(Vector(EMBEDDING_DIMENSIONS))
    chunk_index = Column(Integer, default=0)
    meta_data = Column(JSONB, nullable=True)
    
    source = relationship("Source", back_populates="embeddings")
    page = relationship("Page", back_populates="embeddings")
