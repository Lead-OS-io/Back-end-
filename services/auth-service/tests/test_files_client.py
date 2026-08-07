"""Tests for files_client using httpx.MockTransport (no real network)."""
import io
import json
import uuid

import httpx
import pytest

from app.services.files_client import FilesClient, MediaRef


def _png() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "000000017352474200aece1ce90000000d4944415478da630001000000050001"
        "1a05bbe10000000049454e44ae426082"
    )


def _transport(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        for method, path, response in routes:
            if request.method == method and request.url.path.endswith(path):
                return httpx.Response(response[0], content=json.dumps(response[1]).encode())
        return httpx.Response(404, json={"detail": "not found"})
    return httpx.MockTransport(handler)


def test_upload_avatar_posts_multipart():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(
            201,
            content=json.dumps(
                {
                    "media_id": str(uuid.uuid4()),
                    "bucket": "avatars",
                    "key": "users/x/y.png",
                    "size_bytes": 42,
                    "mimetype": "image/png",
                    "purpose": "profile_photo",
                }
            ).encode(),
        )

    client = FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )
    ref = client.upload_avatar(
        user_id=uuid.uuid4(), content=_png(),
        filename="avatar.png", content_type="image/png",
    )
    assert isinstance(ref, MediaRef)
    assert ref.bucket == "avatars"
    assert captured["method"] == "POST"
    assert captured["content_type"].startswith("multipart/form-data")


def test_get_avatar_parses_payload():
    media_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "media_id": str(media_id),
                "bucket": "avatars",
                "key": "users/x/y.png",
                "size_bytes": 42,
                "mimetype": "image/png",
                "purpose": "profile_photo",
            },
        )

    client = FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )
    ref = client.get_avatar(user_id=uuid.uuid4())
    assert ref.media_id == media_id


def test_get_avatar_404_raises_not_found():
    from shared.utils.exceptions import NotFoundError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "no avatar"})

    client = FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(NotFoundError):
        client.get_avatar(user_id=uuid.uuid4())


def test_presign_returns_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"url": "https://example/foo.png?x=1"})

    client = FilesClient(
        base_url="http://files:8004",
        secret="x", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )
    assert client.presign(media_id=uuid.uuid4(), ttl_seconds=60) == "https://example/foo.png?x=1"


def test_service_token_header_is_attached():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["token"] = request.headers.get("x-service-token", "")
        return httpx.Response(204, content=b"")

    client = FilesClient(
        base_url="http://files:8004",
        secret="mysecret", issuer="auth-service",
        transport=httpx.MockTransport(handler),
    )
    client.delete_avatar(user_id=uuid.uuid4())
    assert captured["token"]
