"""Internal router: avatar read + presign for inter-service callers."""
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.main import create_app
from app.storage.manager import MediaManager
from shared.auth.service_token import mint_service_token

from tests.conftest import FakeStorage


SVC_SECRET = "test-inter-service-secret"


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def fake_storage():
    return FakeStorage()


@pytest.fixture
def settings(fake_storage):
    return type(
        "S2",
        (),
        {
            "INTER_SERVICE_SECRET": SVC_SECRET,
            "PRESIGN_TTL_SECONDS": 300,
            "AVATAR_MAX_BYTES": 5 * 1024 * 1024,
            "AVATAR_ALLOWED_MIMETYPES": ("image/jpeg", "image/png", "image/webp"),
            "STORAGE_BACKEND": "local",
        },
    )()


@pytest.fixture
def client(monkeypatch, engine, fake_storage, settings) -> TestClient:
    monkeypatch.setattr("app.main.get_storage", lambda _settings: fake_storage)
    monkeypatch.setattr("app.internal_router.get_storage", lambda _settings: fake_storage)
    app = create_app()
    headers = {"X-Service-Token": mint_service_token(secret=SVC_SECRET, issuer="test")}
    with TestClient(app, headers=headers) as c:
        app.state.session_factory = lambda: Session(engine)
        app.state.storage = fake_storage
        app.state.settings = settings
        yield c


@pytest.fixture
def client_public(monkeypatch, engine, fake_storage, settings):
    monkeypatch.setattr("app.main.get_storage", lambda _settings: fake_storage)
    app = create_app()
    uid = str(uuid.uuid4())
    with TestClient(app, headers={"X-User-Id": uid}) as c:
        app.state.session_factory = lambda: Session(engine)
        app.state.storage = fake_storage
        app.state.settings = settings
        yield c


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "000000017352474200aece1ce90000000d4944415478da630001000000050001"
        "1a05bbe10000000049454e44ae426082"
    )


def _seed_avatar(user_id: str, client_public):
    """Create a profile photo directly in the shared DB via MediaManager."""
    with Session(client_public.app.state.session_factory().get_bind()) as session:
        manager = MediaManager(db=session, backend=client_public.app.state.storage)
        media = manager.upload_avatar(
            tenant_id=None,
            user_id=uuid.UUID(user_id),
            content=_png_bytes(),
            filename="avatar.png",
            content_type="image/png",
            size_bytes=len(_png_bytes()),
        )
        session.commit()
        return str(media.id)


def test_get_avatar_returns_404_when_missing(client):
    user_id = str(uuid.uuid4())
    resp = client.get(f"/internal/files/users/{user_id}/avatar")
    assert resp.status_code == 404


def test_get_avatar_returns_metadata(client, client_public):
    user_id = client_public.headers.get("X-User-Id")
    _seed_avatar(user_id, client_public)

    resp = client.get(f"/internal/files/users/{user_id}/avatar")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "avatars"
    assert "users/" in body["key"]


def test_presign_endpoint_returns_url(client, client_public):
    user_id = client_public.headers.get("X-User-Id")
    media_id = _seed_avatar(user_id, client_public)

    resp = client.get(f"/internal/files/media/{media_id}/presign", params={"ttl": 30})
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("https://test/")
    assert "?exp=30" in body["url"]


def test_presign_returns_404_for_unknown_media(client):
    resp = client.get(f"/internal/files/media/{uuid.uuid4()}/presign")
    assert resp.status_code == 404
