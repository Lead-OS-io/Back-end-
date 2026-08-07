"""Thin HTTP client to files-service /internal/files/*."""
import io
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

from shared.auth.client import ServiceHttpClient
from shared.utils.exceptions import NotFoundError


@dataclass(frozen=True)
class MediaRef:
    media_id: uuid.UUID
    bucket: str
    key: str
    size_bytes: int
    mimetype: str
    purpose: str


def _from_payload(payload: dict) -> MediaRef:
    return MediaRef(
        media_id=uuid.UUID(payload["media_id"]),
        bucket=payload["bucket"],
        key=payload["key"],
        size_bytes=payload["size_bytes"],
        mimetype=payload["mimetype"],
        purpose=payload["purpose"],
    )


class FilesClient(ServiceHttpClient):
    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        issuer: str,
        timeout: float = 10.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        kwargs = {"timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        super().__init__(
            secret=secret, issuer=issuer, base_url=base_url, **kwargs,
        )

    def upload_avatar(
        self,
        *,
        user_id: uuid.UUID,
        content: bytes,
        filename: str,
        content_type: str,
        x_user_id: Optional[str] = None,
        x_tenant_id: Optional[str] = None,
    ) -> MediaRef:
        files = {"file": (filename, io.BytesIO(content), content_type)}
        headers = {}
        if x_user_id:
            headers["X-User-Id"] = x_user_id
        if x_tenant_id:
            headers["X-Tenant-Id"] = x_tenant_id
        resp = self.post(
            f"/internal/files/users/{user_id}/avatar",
            files=files,
            headers=headers,
        )
        if resp.status_code == 404:
            raise NotFoundError("no avatar")
        resp.raise_for_status()
        return _from_payload(resp.json())

    def get_avatar(self, *, user_id: uuid.UUID) -> MediaRef:
        resp = self.get(f"/internal/files/users/{user_id}/avatar")
        if resp.status_code == 404:
            raise NotFoundError("no avatar")
        resp.raise_for_status()
        return _from_payload(resp.json())

    def delete_avatar(self, *, user_id: uuid.UUID) -> None:
        resp = self.delete(f"/internal/files/users/{user_id}/avatar")
        if resp.status_code == 404:
            return
        resp.raise_for_status()

    def presign(self, *, media_id: uuid.UUID, ttl_seconds: int) -> str:
        resp = self.get(
            f"/internal/files/media/{media_id}/presign",
            params={"ttl": ttl_seconds},
        )
        if resp.status_code == 404:
            raise NotFoundError("media not found")
        resp.raise_for_status()
        return resp.json()["url"]


__all__ = ["FilesClient", "MediaRef"]
