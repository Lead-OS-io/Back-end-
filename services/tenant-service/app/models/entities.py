import uuid
from datetime import datetime

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

    status: TenantStatus = Field(default=TenantStatus.TRIAL, index=True)
    is_active: bool = Field(default=True, nullable=False)

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
