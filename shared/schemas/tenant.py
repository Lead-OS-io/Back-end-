"""
Tenant schemas shared across services.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import Field
import uuid

from shared.schemas.base import BaseSchema


class TenantBase(BaseSchema):
    """Base tenant schema."""
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=63)
    custom_domain: Optional[str] = Field(None, max_length=255)
    status: str = Field(default="trial", max_length=32)


class TenantCreate(TenantBase):
    """Schema for creating a tenant."""
    owner_email: str = Field(..., max_length=255)
    settings: Optional[Dict[str, Any]] = Field(default_factory=dict)
    branding: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TenantUpdate(BaseSchema):
    """Schema for updating a tenant."""
    name: Optional[str] = None
    custom_domain: Optional[str] = None
    status: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    branding: Optional[Dict[str, Any]] = None
    limits: Optional[Dict[str, Any]] = None
    features: Optional[Dict[str, Any]] = None


class TenantSchema(TenantBase):
    """Full tenant schema for responses."""
    id: uuid.UUID
    settings: Dict[str, Any] = Field(default_factory=dict)
    branding: Dict[str, Any] = Field(default_factory=dict)
    limits: Dict[str, Any] = Field(default_factory=dict)
    features: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime
    modified_at: datetime


class TenantInDB(TenantSchema):
    """Tenant schema with all DB fields."""
    cloudflare_zone_id: Optional[str] = None
    cloudflare_custom_hostname_id: Optional[str] = None
    domain_status: str = "pending"
    trial_ends_at: Optional[datetime] = None
    owner_email: Optional[str] = None
    billing_email: Optional[str] = None


class TenantContext(BaseSchema):
    """Minimal tenant context passed between services."""
    id: str
    slug: str
    features: Dict[str, Any] = Field(default_factory=dict)
    limits: Dict[str, Any] = Field(default_factory=dict)

