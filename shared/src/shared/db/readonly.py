from typing import Callable, Generator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session


def create_readonly_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=2, max_overflow=3)
    return create_engine(url, **kwargs)


def readonly_dependency(name: str) -> Callable[[Request], Generator[Session, None, None]]:
    def dep(request: Request) -> Generator[Session, None, None]:
        factories: dict[str, sessionmaker] = request.app.state.readonly_factories
        session: Session = factories[name]()
        try:
            yield session
        finally:
            session.close()

    return dep
