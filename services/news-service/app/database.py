"""
Database configuration for news service
"""
from typing import Generator

from sqlmodel import Session, create_engine
from app.config import settings
import os


engine = create_engine(
    settings.DATABASE_URL, 
    pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "15")),
    pool_pre_ping=True,
    connect_args={"prepare_threshold": None}  # Disable prepared statements for Transaction Mode (port 6543)
)

def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session"""
    with Session(engine) as session:
        yield session


def create_db_and_tables():
    from sqlmodel import SQLModel
    # Import models to ensure they are registered with SQLModel
    from app import models
    SQLModel.metadata.create_all(engine)



