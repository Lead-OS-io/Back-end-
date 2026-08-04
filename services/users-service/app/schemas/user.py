"""
Pydantic schemas for users service
"""
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr, Field

# =============================================================================

class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    country_code: Optional[int] = None
    mobile: Optional[str] = None
    npn: Optional[str] = None
    anpn: Optional[str] = None
    compensation: Optional[int] = None
    job_title: Optional[int] = None
    role_id: Optional[int] = None
    is_individual: Optional[bool] = None
    business_name: Optional[str] = None
    tax_number: Optional[str] = None
    fein: Optional[int] = None
    residential_address: Optional[Dict[str, Any]] = None
    mailing_address: Optional[Dict[str, Any]] = None
    business_address: Optional[Dict[str, Any]] = None
    permissions: Optional[Dict[str, Any]] = None


class UserCreate(UserBase):
    password: str
    tenant_id: UUID
    upline_id: Optional[UUID] = None
    invited_by_id: Optional[UUID] = None
    production_upline_id: Optional[UUID] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    country_code: Optional[int] = None
    mobile: Optional[str] = None
    npn: Optional[str] = None
    anpn: Optional[str] = None
    compensation: Optional[int] = None
    job_title: Optional[int] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_staff: Optional[bool] = None
    is_superuser: Optional[bool] = None
    residential_address: Optional[Dict[str, Any]] = None
    mailing_address: Optional[Dict[str, Any]] = None
    business_address: Optional[Dict[str, Any]] = None
    permissions: Optional[Dict[str, Any]] = None
    upline_id: Optional[UUID] = None
    accepted_campaign_terms_at: Optional[datetime] = None
    opt_in_notes: Optional[str] = None
    accepted_underwriter_terms_at: Optional[datetime] = None


class UserResponse(UserBase):
    id: UUID
    tenant_id: UUID
    is_active: bool
    is_staff: bool
    is_superuser: bool
    date_joined: datetime
    last_login: Optional[datetime]
    upline_id: Optional[UUID]
    invited_by_id: Optional[UUID]
    production_upline_id: Optional[UUID]
    accepted_campaign_terms_at: Optional[datetime] = None
    accepted_underwriter_terms_at: Optional[datetime] = None
    created_at: datetime
    modified_at: datetime

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    size: int
    pages: int
