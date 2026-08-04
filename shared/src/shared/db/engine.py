from typing import Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session


def create_service_engine(
    url: str, *, pool_size: int = 5, max_overflow: int = 10, echo: bool = False
) -> Engine:
    kwargs: dict = {"echo": echo, "pool_pre_ping": True}
    if not url.startswith("sqlite"):
        # SQLite no acepta pool_size/max_overflow
        kwargs.update(pool_size=pool_size, max_overflow=max_overflow)
    return create_engine(url, **kwargs)


def get_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(class_=Session, bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    factory: sessionmaker = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()
