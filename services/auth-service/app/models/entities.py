import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.models.enums import UserStatus


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: Optional[uuid.UUID] = Field(default=None, index=True, nullable=True)
    email: str = Field(unique=True, index=True, max_length=255, nullable=False)
    password_hash: Optional[str] = Field(default=None, max_length=255, nullable=True)
    full_name: Optional[str] = Field(default=None, max_length=255, nullable=True)
    phone: Optional[str] = Field(default=None, max_length=32, nullable=True)
    # status is typed as str so SQLAlchemy ORM does NOT wrap it in an
    # enum instance (which would re-serialize to .name UPPERCASE on
    # flush). The SAEnum column type handles validation against the
    # Postgres ENUM and stores the lowercase .value strings. Pass
    # UserStatus.X.value (a string) when constructing instances.
    status: str = Field(
        default=UserStatus.PENDING_TENANT.value,
        sa_column=Field(
            sa_type=SAEnum(
                UserStatus,
                name="userstatus",
                values_callable=lambda enum: [e.value for e in enum],
            ),
            nullable=False,
            index=True,
        ),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)