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
        AVATAR_ALLOWED_MIMETYPES=("image/jpeg", "image/png", "image/webp"),
        AVATAR_MAX_BYTES=5 * 1024 * 1024,
        PRESIGN_TTL_SECONDS=300,
        FILES_SERVICE_URL="http://files-service:8004",
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


class FakeFilesClient:
    """In-process FilesClient that records calls."""

    def __init__(self, *, not_found: bool = False, urls=None) -> None:
        self.uploads: list = []
        self.deletes: list = []
        self.not_found = not_found
        self._urls = urls or {}
        self._next_id = 1

    def upload_avatar(self, *, user_id, content, filename, content_type, **kw):
        from app.services.files_client import MediaRef

        media_id = _uuid.UUID(int=self._next_id)
        self._next_id += 1
        ref = MediaRef(
            media_id=media_id,
            bucket="avatars",
            key=f"users/{user_id}/y.png",
            size_bytes=len(content),
            mimetype=content_type,
            purpose="profile_photo",
        )
        self.uploads.append(ref)
        return ref

    def get_avatar(self, *, user_id):
        from app.services.files_client import MediaRef

        if self.not_found:
            from shared.utils.exceptions import NotFoundError

            raise NotFoundError("no avatar")
        return MediaRef(
            media_id=_uuid.UUID("11111111-1111-1111-1111-111111111111"),
            bucket="avatars",
            key=f"users/{user_id}/y.png",
            size_bytes=42,
            mimetype="image/png",
            purpose="profile_photo",
        )

    def delete_avatar(self, *, user_id):
        self.deletes.append(user_id)

    def presign(self, *, media_id, ttl_seconds):
        return self._urls.get(media_id, f"https://test/{media_id}.png?ttl={ttl_seconds}")


@pytest.fixture
def fake_files_client() -> FakeFilesClient:
    return FakeFilesClient()


@pytest.fixture
def client(
    settings,
    db_session,
    fake_event_bus,
    svc_headers,
    fake_files_client,
    monkeypatch,
):
    from app.services import avatars as avatars_module

    monkeypatch.setattr(avatars_module, "_FILES_CLIENT_OVERRIDE", fake_files_client)

    from app.main import create_app

    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="x", tenant_id="x", role_id=None, is_superuser=False,
    )
    with TestClient(app) as c:
        c.headers.update(svc_headers)
        yield c
