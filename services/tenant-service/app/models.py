"""
Tenant Service Models.
"""
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum
import uuid
from sqlmodel import Field, SQLModel, JSON


class TenantStatus(str, Enum):
    """Tenant status."""
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class DomainStatus(str, Enum):
    """Domain verification status."""
    PENDING = "pending"
    VERIFYING = "verifying"
    ACTIVE = "active"
    FAILED = "failed"


class Tenant(SQLModel, table=True):
    """Tenant model."""
    __tablename__ = "tenants"
    
    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Basic info
    name: str = Field(max_length=255, index=True)
    slug: str = Field(max_length=63, unique=True, index=True)
    
    # Domain
    custom_domain: Optional[str] = Field(default=None, unique=True, index=True, max_length=255)
    domain_status: DomainStatus = Field(default=DomainStatus.PENDING)
    
    # Cloudflare integration
    cloudflare_zone_id: Optional[str] = Field(default=None, max_length=100)
    cloudflare_custom_hostname_id: Optional[str] = Field(default=None, max_length=100)
    cloudflare_dns_record_id: Optional[str] = Field(default=None, max_length=100)
    
    # Lifecycle (no subscription plans in this project)
    status: TenantStatus = Field(default=TenantStatus.TRIAL)
    trial_ends_at: Optional[datetime] = Field(default=None)
    
    # Contact
    owner_email: Optional[str] = Field(default=None, max_length=255)
    billing_email: Optional[str] = Field(default=None, max_length=255)
    
    # Configuration (JSON fields)
    # IMPORTANT: SQLModel 0.0.31 requires an explicit SQLAlchemy type for dict fields.
    # We use sqlmodel.JSON (no direct sqlalchemy imports).
    settings: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    branding: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    limits: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    features: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    
    # Status
    is_active: bool = Field(default=True)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    modified_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = True


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


DEFAULT_LIMITS: Dict[str, Any] = {
    "users": 0,
    "storage_gb": 0,
    "emails_per_month": 0,
    "api_requests_per_day": 0,
}

DEFAULT_FEATURES: Dict[str, Any] = {}

