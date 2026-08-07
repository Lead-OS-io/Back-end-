"""Internal router for files-service.

Mounted at /internal/files/*. Protected by ServiceTokenMiddleware at the
app level. Not reachable through api-gateway (gateway only routes
/api/<service>/ prefixes).
"""
import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from sqlmodel import Session

from app.config import Settings
from app.models.entities import MediaResources
from app.schemas.internal import MediaRef, PresignResponse
from app.storage import get_storage
from app.storage.manager import MediaManager

router = APIRouter()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _session(request: Request) -> Session:
    return request.app.state.session_factory()


def _manager(request: Request, settings: Settings = Depends(_settings)) -> MediaManager:
    return MediaManager(
        db=_session(request),
        backend=get_storage(settings),
    )


@router.get(
    "/users/{user_id}/avatar",
    response_model=MediaRef,
)
def get_avatar(
    user_id: uuid.UUID,
    manager: MediaManager = Depends(_manager),
) -> MediaRef:
    media = manager.get_avatar(user_id=user_id)
    if media is None:
        raise HTTPException(status_code=404, detail="no avatar")
    return MediaRef(
        media_id=media.id,
        bucket=media.bucket,
        key=media.path,
        size_bytes=media.size_bytes,
        mimetype=media.mimetype,
        purpose=media.purpose,
    )


@router.get(
    "/media/{media_id}/presign",
    response_model=PresignResponse,
)
def presign_media(
    media_id: uuid.UUID,
    ttl: int = 300,
    session: Session = Depends(_session),
    settings: Settings = Depends(_settings),
) -> PresignResponse:
    media: Optional[MediaResources] = session.get(MediaResources, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="media not found")
    backend = get_storage(settings)
    url = backend.presigned_get_url(
        bucket=media.bucket,
        key=media.path,
        expires_seconds=ttl,
    )
    return PresignResponse(url=url)
