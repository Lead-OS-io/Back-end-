"""Tests for the read-only avatars helper used by /me."""
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
import pytest

from app.config import Settings
from app.services.avatars_read import (
    AvatarSummary,
    FilesReadClient,
    _reset_files_read_client_for_tests,
    _set_files_read_client_for_tests,
    get_avatar_summary,
)
from shared.utils.exceptions import NotFoundError


def _settings(**over) -> Settings:
    base = dict(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 32,
        REDIS_URL="redis://x",
        FILES_SERVICE_URL="http://files:8004",
        PRESIGN_TTL_SECONDS=300,
    )
    base.update(over)
    return Settings(**base)


def _files_client(handler) -> FilesReadClient:
    return FilesReadClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )


def test_get_avatar_summary_returns_url_when_remote_has_avatar():
    user_id = uuid.uuid4()
    media_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/presign" in request.url.path:
            return httpx.Response(200, json={"url": "https://example/avatar?sig=1"})
        return httpx.Response(200, json={
            "media_id": str(media_id),
            "bucket": "avatars", "key": f"users/{user_id}/x.png",
            "size_bytes": 100, "mimetype": "image/png", "purpose": "profile_photo",
        })

    summary = get_avatar_summary(
        settings=_settings(), user_id=user_id, files_client=_files_client(handler),
    )
    assert summary.has_avatar is True
    assert summary.avatar_url == "https://example/avatar?sig=1"


def test_get_avatar_summary_returns_false_on_404():
    user_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "missing"})

    summary = get_avatar_summary(
        settings=_settings(), user_id=user_id, files_client=_files_client(handler),
    )
    assert summary.has_avatar is False
    assert summary.avatar_url is None


def test_get_avatar_summary_returns_false_on_5xx_graceful():
    user_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    summary = get_avatar_summary(
        settings=_settings(), user_id=user_id, files_client=_files_client(handler),
    )
    assert summary.has_avatar is False
    assert summary.avatar_url is None


def test_get_avatar_summary_uses_test_override_seam():
    user_id = uuid.uuid4()
    media_id = uuid.uuid4()

    class FakeReadClient:
        def get_avatar(self, *, user_id):
            return _RefStub(media_id=media_id, user_id=user_id)

        def presign(self, *, media_id, ttl_seconds):
            return f"https://fake/{media_id}?ttl={ttl_seconds}"

    _set_files_read_client_for_tests(FakeReadClient())  # type: ignore[arg-type]
    try:
        summary = get_avatar_summary(settings=_settings(), user_id=user_id)
        assert summary.has_avatar is True
        assert summary.avatar_url == f"https://fake/{media_id}?ttl=300"
    finally:
        _reset_files_read_client_for_tests()


@dataclass
class _RefStub:
    media_id: uuid.UUID
    user_id: uuid.UUID
