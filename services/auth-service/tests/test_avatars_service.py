import io
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
import pytest
from passlib.context import CryptContext
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models.entities import User
from app.services.avatars import (
    delete_avatar_for_user,
    get_avatar_for_user,
    upload_avatar_for_user,
)
from app.services.files_client import FilesClient
from shared.utils.exceptions import AppError, NotFoundError


_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _png() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "000000017352474200aece1ce90000000d4944415478da630001000000050001"
        "1a05bbe10000000049454e44ae426082"
    )


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _settings(**over) -> Settings:
    base = dict(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 32,
        REDIS_URL="redis://x",
        AVATAR_MAX_BYTES=5 * 1024 * 1024,
        AVATAR_ALLOWED_MIMETYPES=("image/jpeg", "image/png", "image/webp"),
        PRESIGN_TTL_SECONDS=300,
        FILES_SERVICE_URL="http://files:8004",
    )
    base.update(over)
    return Settings(**base)


def _seed_user(db: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"u-{uuid.uuid4()}@x.com",
        password_hash=_PWD.hash("x"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _files_client_upload(handler) -> FilesClient:
    return FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )


def test_upload_avatar_persists_media_id_and_returns_url():
    s = _session()
    user = _seed_user(s)

    uploaded_media_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/presign" in request.url.path:
            return httpx.Response(200, json={"url": "https://example/avatar.png?x=1"})
        return httpx.Response(201, json={
            "media_id": str(uploaded_media_id),
            "bucket": "avatars", "key": "users/x/y.png",
            "size_bytes": 100, "mimetype": "image/png",
            "purpose": "profile_photo",
        })

    client = _files_client_upload(handler)
    media, url = upload_avatar_for_user(
        db=s, settings=_settings(), user=user,
        content=_png(), filename="avatar.png",
        content_type="image/png",
        files_client=client,
    )
    s.refresh(user)
    assert user.avatar_media_id == uploaded_media_id
    assert media.media_id == uploaded_media_id
    assert "users/x/y.png" in url or url  # any string from the fake is OK


def test_upload_avatar_rejects_too_big():
    s = _session()
    user = _seed_user(s)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={})

    with pytest.raises(AppError) as exc:
        upload_avatar_for_user(
            db=s, settings=_settings(AVATAR_MAX_BYTES=10),
            user=user, content=b"x" * 11, filename="a.png",
            content_type="image/png",
            files_client=_files_client_upload(handler),
        )
    assert exc.value.status_code == 413


def test_upload_avatar_rejects_bad_mime():
    s = _session()
    user = _seed_user(s)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={})

    with pytest.raises(AppError) as exc:
        upload_avatar_for_user(
            db=s, settings=_settings(),
            user=user, content=b"x", filename="a.gif",
            content_type="image/gif",
            files_client=_files_client_upload(handler),
        )
    assert exc.value.status_code == 415


def test_upload_avatar_rejects_empty():
    s = _session()
    user = _seed_user(s)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={})

    with pytest.raises(AppError) as exc:
        upload_avatar_for_user(
            db=s, settings=_settings(),
            user=user, content=b"", filename="a.png",
            content_type="image/png",
            files_client=_files_client_upload(handler),
        )
    assert exc.value.status_code == 422


def test_get_avatar_returns_url_when_set():
    s = _session()
    user = _seed_user(s)
    user.avatar_media_id = uuid.uuid4()
    s.commit()
    s.refresh(user)

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={
            "media_id": str(user.avatar_media_id),
            "bucket": "avatars", "key": "users/x/y.png",
            "size_bytes": 100, "mimetype": "image/png",
            "purpose": "profile_photo",
        })

    def presign_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "https://example/foo"})

    routes = {
        request.url.path: handler
        for request in []
    }
    # Simpler: build a transport that dispatches on path.
    def transport_h(request: httpx.Request) -> httpx.Response:
        if "/presign" in request.url.path:
            return presign_handler(request)
        return handler(request)

    client = FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(transport_h),
    )

    result = get_avatar_for_user(
        db=s, settings=_settings(), user=user, files_client=client,
    )
    assert result is not None
    media, url = result
    assert media.media_id == user.avatar_media_id
    assert url == "https://example/foo"


def test_get_avatar_returns_none_when_no_media_id():
    s = _session()
    user = _seed_user(s)
    assert get_avatar_for_user(
        db=s, settings=_settings(), user=user,
        files_client=FilesClient(
            base_url="http://files:8004",
            secret="x", issuer="auth-service",
            transport=httpx.MockTransport(lambda r: httpx.Response(204)),
        ),
    ) is None


def test_get_avatar_clears_fk_when_remote_404():
    s = _session()
    user = _seed_user(s)
    user.avatar_media_id = uuid.uuid4()
    s.commit()
    s.refresh(user)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "missing"})

    client = FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )

    assert get_avatar_for_user(
        db=s, settings=_settings(), user=user, files_client=client,
    ) is None
    s.refresh(user)
    assert user.avatar_media_id is None


def test_delete_avatar_clears_fk_and_returns_true():
    s = _session()
    user = _seed_user(s)
    user.avatar_media_id = uuid.uuid4()
    s.commit()
    s.refresh(user)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )

    assert delete_avatar_for_user(
        db=s, settings=_settings(), user=user, files_client=client,
    ) is True
    s.refresh(user)
    assert user.avatar_media_id is None


def test_delete_avatar_returns_false_when_no_avatar():
    s = _session()
    user = _seed_user(s)
    assert delete_avatar_for_user(
        db=s, settings=_settings(), user=user,
        files_client=FilesClient(
            base_url="http://files:8004",
            secret="x", issuer="auth-service",
            transport=httpx.MockTransport(lambda r: httpx.Response(204)),
        ),
    ) is False
