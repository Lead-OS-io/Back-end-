"""
Database configuration for Tenant Service.
"""
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine
import os

from app.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "15")),
    pool_pre_ping=True,
    connect_args={
        "options": f"-c search_path={settings.DATABASE_SCHEMA},public",
        "prepare_threshold": None  # Disable prepared statements for Transaction Mode (port 6543)
    },
)


def create_db_and_tables():
    # Tables are managed by Alembic migrations in the public schema.
    # Do NOT create or alter schema here.
    pass



def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        try:
            yield session
        finally:
            session.close()


def get_db() -> Generator[Session, None, None]:
    yield from get_session()

