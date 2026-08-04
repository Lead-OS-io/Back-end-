"""TenantDomain model."""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel

from app.models.tenant import DomainStatus


class TenantDomain(SQLModel, table=True):
    """Additional domains for a tenant."""
    __tablename__ = "tenant_domains"

    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, foreign_key="tenants.id")

    domain: str = Field(unique=True, index=True, max_length=255)
    domain_type: str = Field(default="subdomain", max_length=20)  # subdomain, custom
    status: DomainStatus = Field(default=DomainStatus.PENDING)

    # Cloudflare
    cloudflare_record_id: Optional[str] = Field(default=None, max_length=100)
    cloudflare_hostname_id: Optional[str] = Field(default=None, max_length=100)

    # Verification
    verification_token: Optional[str] = Field(default=None, max_length=100)
    verified_at: Optional[datetime] = Field(default=None)

    # SSL
    ssl_status: str = Field(default="pending", max_length=20)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    modified_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
