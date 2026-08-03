"""
Database configuration for Cases Service.
"""
from typing import Generator
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import Engine

import threading
import os

from app.config import settings

_engine_lock = threading.Lock()
_global_engine: Engine | None = None
_default_pool_size = int(os.getenv("DB_POOL_SIZE", "5"))
_default_max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
_default_pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))


def get_database_engine() -> Engine:
    global _global_engine
    
    if _global_engine is not None:
        try:
            pool = getattr(_global_engine, 'pool', None)
            if pool is None or (hasattr(pool, 'is_closed') and not pool.is_closed()):
                return _global_engine
        except Exception:
            _global_engine = None
    
    with _engine_lock:
        if _global_engine is not None:
            try:
                pool = getattr(_global_engine, 'pool', None)
                if pool is None or (hasattr(pool, 'is_closed') and not pool.is_closed()):
                    return _global_engine
            except Exception:
                _global_engine = None
        

        
        # Optimized for 90 connections (Pool 3+2) and Supavisor Transaction Mode (port 6543)
        _global_engine = create_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            pool_size=15,
            max_overflow=25,
            pool_timeout=30,
            pool_pre_ping=False,
            connect_args={
                "options": f"-c search_path={settings.DATABASE_SCHEMA},public",
                "prepare_threshold": None  # Disable prepared statements for Transaction Mode (port 6543)
            },
        )
            
        return _global_engine


engine = get_database_engine()


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


# Async Database Support
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker

_async_engine_lock = threading.Lock()
_global_async_engine: AsyncEngine | None = None
_async_session_factory = None

def get_async_database_engine() -> AsyncEngine:
    global _global_async_engine
    
    if _global_async_engine is not None:
        return _global_async_engine
    
    with _async_engine_lock:
        if _global_async_engine is not None:
            return _global_async_engine
        
        # Convert postgresql:// to postgresql+asyncpg:// and strip query params (like sslmode) incompatible with asyncpg
        async_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
        if "?" in async_url:
            async_url = async_url.split("?")[0]
        # PgBouncer/Supavisor transaction mode: also pass via URL so asyncpg always disables stmt cache
        async_url = f"{async_url}?statement_cache_size=0"

        # NullPool: no reuse of asyncpg connections. With PgBouncer/Supavisor in transaction mode,
        # pooled connections often break prepared statements (InvalidSQLStatementNameError) even
        # with statement_cache_size=0, because the pooler may swap backends between checkouts.
        _global_async_engine = create_async_engine(
            async_url,
            echo=settings.DEBUG,
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_pre_ping=False,
            connect_args={
                "server_settings": {"search_path": f"{settings.DATABASE_SCHEMA},public"},
                "ssl": "require",
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
            },
        )
        return _global_async_engine

async_engine = get_async_database_engine()
_async_session_factory = sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)

async def get_async_db() -> Generator[AsyncSession, None, None]:
    async with _async_session_factory() as session:
        yield session
