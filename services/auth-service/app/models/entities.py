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
    # values_callable forces SQLAlchemy to use the lowercase .value
    # strings ("pending_tenant", "active", "disabled") instead of the
    # uppercase .name ("PENDING_TENANT", ...) when persisting to the
    # Postgres ENUM type created by the migration.
    status: UserStatus = Field(
        default=UserStatus.PENDING_TENANT,
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