"""Public router for files-service.

Mounted at /public/files/*. Protected by PublicAuthMiddleware (validates
X-User-Id). The api-gateway decodes the user JWT and forwards with
X-User-Id / X-Tenant-Id / X-Is-Superuser headers; we resolve `me` from
X-User-Id server-side and enforce ownership.

Endpoints:
- POST   /users/me/avatar          upload (replace), 201 + MediaRef
- GET    /users/me/avatar          302 -> presigned URL
- DELETE /users/me/avatar          204
- GET    /media/{media_id}/presign 302 -> presigned URL (ownership enforced)
"""
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.auth import Identity, get_current_identity
from app.config import Settings
from app.models.entities import MediaResources
from app.schemas.internal import MediaRef
from app.storage.manager import MediaManager
from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope


_log = logging.getLogger(__name__)

router = APIRouter()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _session(request: Request) -> Session:
    return request.app.state.session_factory()


def _manager(request: Request) -> MediaManager:
    return MediaManager(db=_session(request), backend=request.app.state.storage)


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _publish_event(envelope: EventEnvelope) -> None:
    """Publish an event, swallowing infrastructure errors per spec §7.4."""
    try:
        EventBus(_redis_url()).publish("onboarding", envelope)
    except Exception:  # pragma: no cover — defensive
        _log.warning("failed to publish event %s", envelope.type, exc_info=True)


def _validate_upload(*, content: bytes, content_type: str, settings: Settings) -> None:
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="empty file")
    if len(content) > settings.AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds maximum {settings.AVATAR_MAX_BYTES} bytes",
        )
    if content_type not in settings.AVATAR_ALLOWED_MIMETYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported content type; allowed: {list(settings.AVATAR_ALLOWED_MIMETYPES)}",
        )


def _to_media_ref(media: MediaResources) -> MediaRef:
    return MediaRef(
        media_id=media.id,
        bucket=media.bucket,
        key=media.path,
        size_bytes=media.size_bytes,
        mimetype=media.mimetype,
        purpose=media.purpose,
    )


@router.post(
    "/users/me/avatar",
    response_model=MediaRef,
    status_code=201,
)
def upload_my_avatar(
    file: UploadFile = File(...),
    identity: Identity = Depends(get_current_identity),
    manager: MediaManager = Depends(_manager),
    settings: Settings = Depends(_settings),
):
    content = file.file.read()
    content_type = file.content_type or "application/octet-stream"
    _validate_upload(content=content, content_type=content_type, settings=settings)
    media = manager.upload_avatar(
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        content=content,
        filename=file.filename or "avatar.bin",
        content_type=content_type,
        size_bytes=len(content),
    )
    _publish_event(
        EventEnvelope(
            type="user.avatar.changed",
            aggregate_id=str(identity.user_id),
            tenant_id=str(identity.tenant_id) if identity.tenant_id else None,
            payload={
                "user_id": str(identity.user_id),
                "media_id": str(media.id),
                "mimetype": media.mimetype,
                "size_bytes": media.size_bytes,
            },
        )
    )
    return _to_media_ref(media)


@router.get("/users/me/avatar")
def get_my_avatar(
    identity: Identity = Depends(get_current_identity),
    manager: MediaManager = Depends(_manager),
    settings: Settings = Depends(_settings),
):
    media = manager.get_avatar(user_id=identity.user_id)
    if media is None:
        raise HTTPException(status_code=404, detail="no avatar")
    url = manager.presigned_url_for(media=media, ttl_seconds=settings.PRESIGN_TTL_SECONDS)
    return RedirectResponse(url=url, status_code=302)


@router.delete("/users/me/avatar", status_code=204)
def delete_my_avatar(
    identity: Identity = Depends(get_current_identity),
    manager: MediaManager = Depends(_manager),
):
    if not manager.delete_avatar(user_id=identity.user_id):
        raise HTTPException(status_code=404, detail="no avatar")
    _publish_event(
        EventEnvelope(
            type="user.avatar.removed",
            aggregate_id=str(identity.user_id),
            tenant_id=str(identity.tenant_id) if identity.tenant_id else None,
            payload={"user_id": str(identity.user_id)},
        )
    )
    return None


@router.get("/media/{media_id}/presign")
def presign_media_public(
    media_id: uuid.UUID,
    request: Request,
    ttl: int = 300,
    identity: Identity = Depends(get_current_identity),
    session: Session = Depends(_session),
    settings: Settings = Depends(_settings),
):
    media: Optional[MediaResources] = session.get(MediaResources, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="media not found")
    if media.user_id != identity.user_id:
        raise HTTPException(status_code=403, detail="not the owner")
    effective_ttl = max(1, min(ttl, settings.PRESIGN_TTL_SECONDS))
    manager = MediaManager(db=session, backend=request.app.state.storage)
    url = manager.presigned_url_for(media=media, ttl_seconds=effective_ttl)
    return RedirectResponse(url=url, status_code=302)


__all__ = ["router"]
