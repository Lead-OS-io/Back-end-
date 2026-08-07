import os

os.environ.setdefault("SERVICE_NAME", "auth-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import uuid as _uuid
from typing import Iterator

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models.entities import User
from app.models.enums import UserStatus
from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.service_token import mint_service_token
from shared.db.engine import get_db

INTER_SERVICE_SECRET = "test-inter-service-secret"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET=INTER_SERVICE_SECRET,
        SECRET_KEY="test-secret-key-0123456789abcdef",
        REDIS_URL="redis://localhost:6379/15",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_MINUTES=60,
        FILES_SERVICE_URL="http://files-service:8004",
        PRESIGN_TTL_SECONDS=300,
        COOKIE_SECURE=False,
        COOKIE_SAMESITE="lax",
        COOKIE_PATH="/api/auth",
        COOKIE_DOMAIN="",
    )


@pytest.fixture
def identity() -> Identity:
    return Identity(
        user_id="00000000-0000-0000-0000-000000000001",
        tenant_id="00000000-0000-0000-0000-000000000002",
        role_id=1,
        is_superuser=True,
    )


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def fake_event_bus(monkeypatch):
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **k: fakeredis.FakeRedis(decode_responses=True),
    )
    from shared.events.bus import EventBus

    return EventBus("redis://localhost:6379/15")


@pytest.fixture
def svc_headers() -> dict[str, str]:
    return {"X-Service-Token": mint_service_token(secret=INTER_SERVICE_SECRET, issuer="test")}


class FakeFilesReadClient:
    """In-process stand-in for FilesReadClient used by avatars_read."""

    def __init__(self) -> None:
        self.has_avatar = False
        self.url = None
        self.calls = {"get_avatar": 0, "presign": 0}

    def set_has_avatar(self, has_avatar: bool, *, url: str | None = None) -> None:
        self.has_avatar = has_avatar
        self.url = url

    def get_avatar(self, *, user_id):
        from shared.utils.exceptions import NotFoundError

        self.calls["get_avatar"] += 1
        if not self.has_avatar:
            raise NotFoundError("no avatar")
        return _FakeRef(media_id=_uuid.uuid4(), user_id=user_id)

    def presign(self, *, media_id, ttl_seconds):
        self.calls["presign"] += 1
        return self.url or f"https://test/{media_id}.png?ttl={ttl_seconds}"


class _FakeRef:
    def __init__(self, *, media_id, user_id):
        self.media_id = media_id
        self.user_id = user_id
        self.bucket = "avatars"
        self.key = f"users/{user_id}/x.png"
        self.size_bytes = 42
        self.mimetype = "image/png"
        self.purpose = "profile_photo"


@pytest.fixture
def fake_files_read_client() -> FakeFilesReadClient:
    return FakeFilesReadClient()


@pytest.fixture
def client(
    settings,
    db_session,
    fake_event_bus,
    svc_headers,
    fake_files_read_client,
    monkeypatch,
):
    from app.services import avatars_read as avatars_read_module

    monkeypatch.setattr(
        avatars_read_module, "_FILES_READ_CLIENT_OVERRIDE", fake_files_read_client,
    )

    from app.main import create_app

    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="x", tenant_id="x", role_id=None, is_superuser=False,
    )
    with TestClient(app) as c:
        c.headers.update(svc_headers)
        yield c
