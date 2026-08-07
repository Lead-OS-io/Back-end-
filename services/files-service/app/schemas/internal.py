from uuid import UUID

from pydantic import BaseModel

from app.models.enums import MediaPurpose


class MediaRef(BaseModel):
    media_id: UUID
    bucket: str
    key: str
    size_bytes: int
    mimetype: str
    purpose: MediaPurpose


class PresignResponse(BaseModel):
    url: str
