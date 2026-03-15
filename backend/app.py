# Fix for Windows: Set HF_HUB env vars before any imports to prevent symlink errors
import os
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ingestion.router import ingestion_router

from shared import preflight_pgvector
from shared.logger import logger
from agents.router import agent_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Firecrawl-Docling RAG API...")
    preflight_pgvector()
    
    logger.success("Lifespan: Pre-flight checks complete")
    yield
    # Shutdown
    logger.warning("Firecrawl-Docling RAG API shutting down...")


app = FastAPI(title="Firecrawl-Docling RAG API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router, prefix="/api")
app.include_router(ingestion_router, prefix="/api")
