"""Avatar orchestration in auth-service.

Validates the upload locally (size, mime, non-empty), then delegates to
files-service. Keeps users.avatar_media_id coherent with the remote state.
"""
import uuid
from typing import Optional, Tuple

from sqlmodel import Session

from app.config import Settings
from app.models.entities import User
from app.services.files_client import FilesClient, MediaRef
from shared.utils.exceptions import AppError, NotFoundError


_FILES_CLIENT_OVERRIDE: Optional[FilesClient] = None


def _set_files_client_for_tests(client: Optional[FilesClient]) -> None:
    """Test seam: monkey-patch the module-level FilesClient override."""
    global _FILES_CLIENT_OVERRIDE
    _FILES_CLIENT_OVERRIDE = client


def _reset_files_client_for_tests() -> None:
    """Test seam: clear the module-level FilesClient override."""
    global _FILES_CLIENT_OVERRIDE
    _FILES_CLIENT_OVERRIDE = None


def _resolve_files_client(
    files_client: Optional[FilesClient],
) -> FilesClient:
    """Return the test override if set, otherwise the injected client.

    Production callers construct a client per request and pass it in.
    Tests may prefer the monkey-patched override to avoid threading the
    dependency through every helper.
    """
    if files_client is not None:
        return files_client
    if _FILES_CLIENT_OVERRIDE is not None:
        return _FILES_CLIENT_OVERRIDE
    raise AppError(500, "files_client not configured")


def _validate_upload(*, content: bytes, content_type: str, settings: Settings) -> None:
    if len(content) == 0:
        raise AppError(422, "empty file")
    if len(content) > settings.AVATAR_MAX_BYTES:
        raise AppError(413, f"file exceeds maximum {settings.AVATAR_MAX_BYTES} bytes")
    if content_type not in settings.AVATAR_ALLOWED_MIMETYPES:
        allowed = list(settings.AVATAR_ALLOWED_MIMETYPES)
        raise AppError(415, f"unsupported content type; allowed: {allowed}")


def get_avatar_for_user(
    *,
    db: Session,
    settings: Settings,
    user: User,
    files_client: Optional[FilesClient] = None,
) -> Optional[Tuple[MediaRef, str]]:
    if user.avatar_media_id is None:
        return None
    client = _resolve_files_client(files_client)
    try:
        media = client.get_avatar(user_id=user.id)
    except NotFoundError:
        user.avatar_media_id = None
        db.commit()
        db.refresh(user)
        return None
    url = client.presign(
        media_id=media.media_id,
        ttl_seconds=settings.PRESIGN_TTL_SECONDS,
    )
    return media, url


def upload_avatar_for_user(
    *,
    db: Session,
    settings: Settings,
    user: User,
    content: bytes,
    filename: str,
    content_type: str,
    files_client: Optional[FilesClient] = None,
) -> Tuple[MediaRef, str]:
    _validate_upload(content=content, content_type=content_type, settings=settings)
    client = _resolve_files_client(files_client)
    media = client.upload_avatar(
        user_id=user.id,
        content=content,
        filename=filename,
        content_type=content_type,
    )
    user.avatar_media_id = media.media_id
    db.commit()
    db.refresh(user)
    url = client.presign(
        media_id=media.media_id,
        ttl_seconds=settings.PRESIGN_TTL_SECONDS,
    )
    return media, url


def delete_avatar_for_user(
    *,
    db: Session,
    settings: Settings,
    user: User,
    files_client: Optional[FilesClient] = None,
) -> bool:
    if user.avatar_media_id is None:
        return False
    client = _resolve_files_client(files_client)
    client.delete_avatar(user_id=user.id)
    user.avatar_media_id = None
    db.commit()
    db.refresh(user)
    return True


__all__ = [
    "get_avatar_for_user",
    "upload_avatar_for_user",
    "delete_avatar_for_user",
    "_set_files_client_for_tests",
    "_reset_files_client_for_tests",
]
