"""Read-only avatar helper for /me, /login, /refresh, PATCH /me enrichment.

Calls files-service /internal/files/users/{id}/avatar + /media/{id}/presign
and returns a tiny AvatarSummary. No side effects: avatar ownership lives
in files-service now (media_resources.user_id), so there is no FK in auth_db
to clean up.

The HTTP client shape mirrors FilesClient from the deleted
app.services.files_client, but reduced to the two read methods we need.
"""
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import Settings
from shared.auth.client import ServiceHttpClient
from shared.utils.exceptions import NotFoundError


@dataclass(frozen=True)
class AvatarSummary:
    has_avatar: bool
    avatar_url: Optional[str]


@dataclass(frozen=True)
class MediaRef:
    media_id: uuid.UUID
    bucket: str
    key: str
    size_bytes: int
    mimetype: str
    purpose: str


class FilesReadClient(ServiceHttpClient):
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
        super().__init__(secret=secret, issuer=issuer, base_url=base_url, **kwargs)

    def get_avatar(self, *, user_id: uuid.UUID) -> MediaRef:
        resp = self.get(f"/internal/files/users/{user_id}/avatar")
        if resp.status_code == 404:
            raise NotFoundError("no avatar")
        resp.raise_for_status()
        body = resp.json()
        return MediaRef(
            media_id=uuid.UUID(body["media_id"]),
            bucket=body["bucket"],
            key=body["key"],
            size_bytes=body["size_bytes"],
            mimetype=body["mimetype"],
            purpose=body["purpose"],
        )

    def presign(self, *, media_id: uuid.UUID, ttl_seconds: int) -> str:
        resp = self.get(
            f"/internal/files/media/{media_id}/presign",
            params={"ttl": ttl_seconds},
        )
        if resp.status_code == 404:
            raise NotFoundError("media not found")
        resp.raise_for_status()
        return resp.json()["url"]


_FILES_READ_CLIENT_OVERRIDE: Optional[FilesReadClient] = None


def _set_files_read_client_for_tests(client: Optional[FilesReadClient]) -> None:
    global _FILES_READ_CLIENT_OVERRIDE
    _FILES_READ_CLIENT_OVERRIDE = client


def _reset_files_read_client_for_tests() -> None:
    global _FILES_READ_CLIENT_OVERRIDE
    _FILES_READ_CLIENT_OVERRIDE = None


def _resolve_read_client(
    settings: Settings,
    files_client: Optional[FilesReadClient],
) -> FilesReadClient:
    if files_client is not None:
        return files_client
    if _FILES_READ_CLIENT_OVERRIDE is not None:
        return _FILES_READ_CLIENT_OVERRIDE
    return FilesReadClient(
        base_url=settings.FILES_SERVICE_URL,
        secret=settings.INTER_SERVICE_SECRET,
        issuer=settings.SERVICE_NAME,
    )


def get_avatar_summary(
    *,
    settings: Settings,
    user_id: uuid.UUID,
    files_client: Optional[FilesReadClient] = None,
) -> AvatarSummary:
    client = _resolve_read_client(settings, files_client)
    try:
        media = client.get_avatar(user_id=user_id)
    except NotFoundError:
        return AvatarSummary(has_avatar=False, avatar_url=None)
    except Exception:
        # 5xx, timeout, or anything else: graceful degradation per spec §7.3.
        return AvatarSummary(has_avatar=False, avatar_url=None)
    try:
        url = client.presign(media_id=media.media_id, ttl_seconds=settings.PRESIGN_TTL_SECONDS)
    except Exception:
        return AvatarSummary(has_avatar=False, avatar_url=None)
    return AvatarSummary(has_avatar=True, avatar_url=url)


__all__ = [
    "AvatarSummary",
    "FilesReadClient",
    "MediaRef",
    "_reset_files_read_client_for_tests",
    "_set_files_read_client_for_tests",
    "get_avatar_summary",
]
