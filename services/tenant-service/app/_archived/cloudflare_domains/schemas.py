"""
Tenant Service Pydantic Schemas.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
import uuid

from app.models import TenantStatus, DomainStatus


# Request schemas
class TenantCreateRequest(BaseModel):
    """Create tenant request."""
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=63, pattern="^[a-z0-9-]+$")
    owner_email: EmailStr
    settings: Optional[Dict[str, Any]] = None
    branding: Optional[Dict[str, Any]] = None


class TenantUpdateRequest(BaseModel):
    """Update tenant request."""
    name: Optional[str] = None
    status: Optional[TenantStatus] = None
    settings: Optional[Dict[str, Any]] = None
    branding: Optional[Dict[str, Any]] = None
    limits: Optional[Dict[str, Any]] = None
    features: Optional[Dict[str, Any]] = None
    billing_email: Optional[EmailStr] = None


class DomainCreateRequest(BaseModel):
    """Create domain request."""
    domain: str = Field(..., max_length=255)
    domain_type: str = Field(default="custom", pattern="^(subdomain|custom)$")


class SubdomainCreateRequest(BaseModel):
    """Create subdomain request."""
    subdomain: str = Field(..., max_length=63, pattern="^[a-z0-9-]+$")


# Response schemas
class TenantResponse(BaseModel):
    """Tenant response."""
    id: uuid.UUID
    name: str
    slug: str
    custom_domain: Optional[str]
    domain_status: DomainStatus
    status: TenantStatus
    is_active: bool
    created_at: datetime
    modified_at: datetime
    
    class Config:
        from_attributes = True


class TenantDetailResponse(TenantResponse):
    """Tenant detail response with all fields."""
    owner_email: Optional[str]
    billing_email: Optional[str]
    settings: Dict[str, Any]
    branding: Dict[str, Any]
    limits: Dict[str, Any]
    features: Dict[str, Any]
    trial_ends_at: Optional[datetime]


class DomainResponse(BaseModel):
    """Domain response."""
    id: uuid.UUID
    domain: str
    domain_type: str
    status: DomainStatus
    ssl_status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class DomainVerificationResponse(BaseModel):
    """Domain verification instructions."""
    domain: str
    status: DomainStatus
    verification_type: str
    verification_record: Dict[str, str]
    instructions: str


class TenantContextResponse(BaseModel):
    """Minimal tenant context for other services."""
    id: str
    slug: str
    features: Dict[str, Any]
    limits: Dict[str, Any]


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    cloudflare_connected: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)

