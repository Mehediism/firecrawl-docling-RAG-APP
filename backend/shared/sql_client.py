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
    
