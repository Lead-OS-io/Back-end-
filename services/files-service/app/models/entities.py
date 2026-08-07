import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Column
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.enums import MediaPurpose, MediaType


class MediaResources(SQLModel, table=True):
    __tablename__ = "media_resources"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    tenant_id: Optional[uuid.UUID] = Field(default=None, index=True, nullable=True)
    user_id: Optional[uuid.UUID] = Field(default=None, index=True, nullable=True)

    original_filename: str = Field(nullable=False)
    media_type: MediaType = Field(
        sa_column=Column(SAEnum(MediaType, name="media_type"), nullable=False, index=True),
    )
    purpose: MediaPurpose = Field(
        sa_column=Column(SAEnum(MediaPurpose, name="media_purpose"), nullable=False, index=True),
    )
    mimetype: str = Field(nullable=False)
    format: str = Field(nullable=False)
    size_bytes: int = Field(sa_type=BigInteger, nullable=False)

    bucket: str = Field(nullable=False)
    path: str = Field(nullable=False)
    is_public: bool = Field(default=False, nullable=False, index=True)

    duration: Optional[int] = Field(default=None, nullable=True)
    meta: dict = Field(
        default_factory=dict,
        sa_type=JSONB,
        sa_column_kwargs={"name": "metadata"},
        nullable=False,
    )
    sort_order: Optional[int] = Field(default=None, nullable=True, sa_column_kwargs={"server_default": "0"})

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)

    class Config:
        arbitrary_types_allowed = True
