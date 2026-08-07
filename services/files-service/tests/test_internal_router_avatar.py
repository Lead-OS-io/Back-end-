"""Internal router: avatar upload/get/delete for users."""
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.main import create_app
from app.storage import get_storage
from shared.auth.service_token import mint_service_token

from tests.conftest import FakeStorage


SVC_SECRET = "test-inter-service-secret"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    fake = FakeStorage()
    monkeypatch.setattr(
        "app.internal_router.get_storage",
        lambda _settings: fake,
    )

    settings = type("S", (), {})()
    settings.SECRET_KEY = "test-secret-key-0123456789abcdef"

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app = create_app()
    headers = {"X-Service-Token": mint_service_token(secret=SVC_SECRET, issuer="test")}
    with TestClient(app, headers=headers) as c:
        app.state.session_factory = lambda: Session(engine)
        app.state.storage = fake
        app.state.settings = type(
            "S2", (), {"INTER_SERVICE_SECRET": SVC_SECRET, "PRESIGN_TTL_SECONDS": 300}
        )()
        yield c


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "000000017352474200aece1ce90000000d4944415478da630001000000050001"
        "1a05bbe10000000049454e44ae426082"
    )


def test_upload_avatar_returns_201_and_creates_row(client):
    user_id = str(uuid.uuid4())
    files = {"file": ("avatar.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = client.post(
        f"/internal/files/users/{user_id}/avatar",
        files=files,
        headers={"X-User-Id": user_id},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["bucket"] == "avatars"
    assert body["size_bytes"] > 0
    assert body["mimetype"] == "image/png"


def test_get_avatar_returns_404_when_missing(client):
    user_id = str(uuid.uuid4())
    resp = client.get(f"/internal/files/users/{user_id}/avatar")
    assert resp.status_code == 404


def test_get_avatar_returns_metadata(client):
    user_id = str(uuid.uuid4())
    files = {"file": ("avatar.png", io.BytesIO(_png_bytes()), "image/png")}
    client.post(
        f"/internal/files/users/{user_id}/avatar",
        files=files,
        headers={"X-User-Id": user_id},
    )
    resp = client.get(f"/internal/files/users/{user_id}/avatar")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "avatars"
    assert "users/" in body["key"]


def test_delete_avatar_returns_204(client):
    user_id = str(uuid.uuid4())
    files = {"file": ("avatar.png", io.BytesIO(_png_bytes()), "image/png")}
    client.post(
        f"/internal/files/users/{user_id}/avatar",
        files=files,
        headers={"X-User-Id": user_id},
    )
    resp = client.delete(f"/internal/files/users/{user_id}/avatar")
    assert resp.status_code == 204
    assert client.get(f"/internal/files/users/{user_id}/avatar").status_code == 404


def test_presign_endpoint_returns_url(client):
    user_id = str(uuid.uuid4())
    files = {"file": ("avatar.png", io.BytesIO(_png_bytes()), "image/png")}
    up = client.post(
        f"/internal/files/users/{user_id}/avatar",
        files=files,
        headers={"X-User-Id": user_id},
    )
    media_id = up.json()["media_id"]
    resp = client.get(f"/internal/files/media/{media_id}/presign", params={"ttl": 30})
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].startswith("https://test/")
    assert "?exp=30" in body["url"]


def test_presign_returns_404_for_unknown_media(client):
    resp = client.get(f"/internal/files/media/{uuid.uuid4()}/presign")
    assert resp.status_code == 404
