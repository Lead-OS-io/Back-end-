import os

os.environ.setdefault("SERVICE_NAME", "auth-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import User, UserStatus
from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.service_token import mint_service_token
from shared.db.engine import get_db
from shared.events.bus import EventBus

INTER_SERVICE_SECRET = "test-inter-service-secret"


@pytest.fixture
def identity() -> Identity:
    return Identity(user_id="00000000-0000-0000-0000-000000000001",
                    tenant_id="00000000-0000-0000-0000-000000000002",
                    role_id=1, is_superuser=True)


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
    bus = EventBus("redis://localhost:6379/15")
    return bus


@pytest.fixture
def svc_headers() -> dict[str, str]:
    return {"X-Service-Token": mint_service_token(secret=INTER_SERVICE_SECRET, issuer="test")}


@pytest.fixture
def client(fake_event_bus, db_session, svc_headers):
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="x", tenant_id="x", role_id=None, is_superuser=False
    )
    with TestClient(app) as c:
        c.headers.update(svc_headers)
        yield c
