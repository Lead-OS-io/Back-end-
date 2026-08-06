import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.models.enums import TenantStatus


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, nullable=False)
    slug: str = Field(max_length=63, unique=True, index=True, nullable=False)

    business_name: str = Field(max_length=255, nullable=False)
    timezone: str = Field(max_length=64, nullable=False)
    legal_name: str = Field(max_length=255, nullable=False)
    support_inbox: str = Field(max_length=255, nullable=False)

    # status is typed as str so SQLAlchemy ORM does NOT wrap it in an
    # enum instance (which would re-serialize to .name UPPERCASE on
    # flush). The SAEnum column type handles validation against the
    # Postgres ENUM and stores the lowercase .value strings. Pass
    # TenantStatus.X.value (a string) when constructing instances.
    status: str = Field(
        default=TenantStatus.TRIAL.value,
        sa_column=Field(
            sa_type=SAEnum(
                TenantStatus,
                name="tenantstatus",
                values_callable=lambda enum: [e.value for e in enum],
            ),
            nullable=False,
            index=True,
        ),
    )
    is_active: bool = Field(default=True, nullable=False)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)