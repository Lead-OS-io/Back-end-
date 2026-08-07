from uuid import UUID

from pydantic import BaseModel


class AvatarResponse(BaseModel):
    media_id: UUID
    avatar_url: str
    size_bytes: int
    mimetype: str
