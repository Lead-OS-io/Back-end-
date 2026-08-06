import os

os.environ.setdefault("SERVICE_NAME", "tenant-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import fakeredis
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from shared.events.bus import EventBus


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def fake_event_bus(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **k: fakeredis.FakeRedis(decode_responses=True),
    )
    return EventBus("redis://localhost:6379/15")
