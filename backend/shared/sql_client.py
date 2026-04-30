import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from shared.logger import logger
from contextlib import contextmanager
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import SQLAlchemyError


load_dotenv()

DB_URL_SQLAlchemy = os.environ['DATABASE_URL']

engine = create_engine(DB_URL_SQLAlchemy)
Base = declarative_base()

@contextmanager
def get_pg_session():
    session = Session(engine)
    try:
        yield session
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()

def preflight_pgvector():
    with get_pg_session() as session:
        session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        session.commit()
    Base.metadata.create_all(engine)

    # BM25 / full-text search column + index. Idempotent.
    # Uses 'simple' config (no language-specific stemming) so it works for
    # English, Bangla, and mixed multilingual content uniformly.
    with get_pg_session() as session:
        session.execute(text("""
            ALTER TABLE embeddings
            ADD COLUMN IF NOT EXISTS content_tsv tsvector
            GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS embeddings_content_tsv_idx
            ON embeddings USING GIN (content_tsv)
        """))
        session.commit()
        logger.info("Preflight: BM25 tsvector column + GIN index ready")
