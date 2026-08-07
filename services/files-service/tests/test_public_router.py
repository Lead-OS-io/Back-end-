"""Public router: avatar upload/get/delete + presign with ownership."""
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.main import create_app
from app.storage import get_storage
from tests.conftest import FakeStorage


SVC_SECRET = "test-inter-service-secret"


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "000000017352474200aece1ce90000000d4944415478da630001000000050001"
        "1a05bbe10000000049454e44ae426082"
    )


@pytest.fixture
def public_client(monkeypatch) -> TestClient:
    fake = FakeStorage()
    monkeypatch.setattr("app.main.get_storage", lambda _settings: fake)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app = create_app()
    uid = str(uuid.uuid4())
    with TestClient(app, headers={"X-User-Id": uid}) as c:
        app.state.session_factory = lambda: Session(engine)
        app.state.storage = fake
        app.state.settings = type(
            "S",
            (),
            {
                "INTER_SERVICE_SECRET": SVC_SECRET,
                "PRESIGN_TTL_SECONDS": 300,
                "AVATAR_MAX_BYTES": 5 * 1024 * 1024,
                "AVATAR_ALLOWED_MIMETYPES": ("image/jpeg", "image/png", "image/webp"),
                "STORAGE_BACKEND": "local",
            },
        )()
        yield c


def test_upload_returns_201_and_creates_row(public_client):
    files = {"file": ("avatar.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["bucket"] == "avatars"
    assert body["size_bytes"] > 0
    assert body["mimetype"] == "image/png"
    assert body["purpose"] == "profile_photo"


def test_upload_replaces_existing(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    first = public_client.post("/public/files/users/me/avatar", files=files).json()
    files2 = {"file": ("b.png", io.BytesIO(_png_bytes()), "image/png")}
    second = public_client.post("/public/files/users/me/avatar", files=files2).json()
    assert first["media_id"] != second["media_id"]
    listing = public_client.get("/public/files/users/me/avatar", allow_redirects=False)
    assert listing.status_code == 302
    assert first["media_id"] not in listing.headers["location"]


def test_upload_rejects_oversize(public_client):
    big = b"x" * (5 * 1024 * 1024 + 1)
    files = {"file": ("a.png", io.BytesIO(big), "image/png")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 413


def test_upload_rejects_bad_mime(public_client):
    files = {"file": ("a.gif", io.BytesIO(_png_bytes()), "image/gif")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 400


def test_upload_rejects_empty(public_client):
    files = {"file": ("a.png", io.BytesIO(b""), "image/png")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 400


def test_upload_without_identity_is_401():
    from fastapi.testclient import TestClient as _TC

    from app.main import create_app

    app = create_app()
    with _TC(app) as c:
        files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
        resp = c.post("/public/files/users/me/avatar", files=files)
        assert resp.status_code == 401


def test_get_avatar_returns_302_with_presigned_url(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    public_client.post("/public/files/users/me/avatar", files=files)
    resp = public_client.get("/public/files/users/me/avatar", allow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://test/")
    assert "?exp=300" in resp.headers["location"]


def test_get_avatar_returns_404_when_missing(public_client):
    resp = public_client.get("/public/files/users/me/avatar", allow_redirects=False)
    assert resp.status_code == 404


def test_delete_avatar_returns_204(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    public_client.post("/public/files/users/me/avatar", files=files)
    resp = public_client.delete("/public/files/users/me/avatar")
    assert resp.status_code == 204
    assert public_client.get("/public/files/users/me/avatar").status_code == 404


def test_delete_avatar_returns_404_when_missing(public_client):
    resp = public_client.delete("/public/files/users/me/avatar")
    assert resp.status_code == 404


def test_presign_endpoint_enforces_ownership(public_client):
    """User A uploads; user B cannot presign A's media."""
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    up = public_client.post("/public/files/users/me/avatar", files=files)
    media_id = up.json()["media_id"]

    # Switch to user B
    other = str(uuid.uuid4())
    public_client.headers["X-User-Id"] = other
    resp = public_client.get(f"/public/files/media/{media_id}/presign")
    assert resp.status_code == 403


def test_presign_endpoint_happy_path(public_client):
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    up = public_client.post("/public/files/users/me/avatar", files=files)
    media_id = up.json()["media_id"]
    resp = public_client.get(
        f"/public/files/media/{media_id}/presign",
        params={"ttl": 60},
        allow_redirects=False,
    )
    assert resp.status_code == 302
    assert "?exp=60" in resp.headers["location"]


def test_presign_endpoint_404_for_unknown_media(public_client):
    resp = public_client.get(f"/public/files/media/{uuid.uuid4()}/presign")
    assert resp.status_code == 404


def test_upload_publishes_user_avatar_changed(public_client, monkeypatch):
    captured = []
    monkeypatch.setattr(
        "app.public_router._publish_event",
        lambda envelope: captured.append(envelope),
    )
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    resp = public_client.post("/public/files/users/me/avatar", files=files)
    assert resp.status_code == 201
    assert len(captured) == 1
    envelope = captured[0]
    assert envelope.type == "user.avatar.changed"
    assert envelope.payload["media_id"] == resp.json()["media_id"]
    assert envelope.payload["mimetype"] == "image/png"


def test_delete_publishes_user_avatar_removed(public_client, monkeypatch):
    captured = []
    monkeypatch.setattr(
        "app.public_router._publish_event",
        lambda envelope: captured.append(envelope),
    )
    files = {"file": ("a.png", io.BytesIO(_png_bytes()), "image/png")}
    public_client.post("/public/files/users/me/avatar", files=files)
    del_resp = public_client.delete("/public/files/users/me/avatar")
    assert del_resp.status_code == 204
    assert len(captured) == 2
    envelope = captured[-1]
    assert envelope.type == "user.avatar.removed"
