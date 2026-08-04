"""
Pydantic schemas for users service
"""
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr

# =============================================================================

class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role_id: Optional[int] = None
    permissions: Optional[Dict[str, Any]] = None


class UserCreate(UserBase):
    password: str
    tenant_id: UUID


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_staff: Optional[bool] = None
    is_superuser: Optional[bool] = None
    permissions: Optional[Dict[str, Any]] = None


class UserResponse(UserBase):
    id: UUID
    tenant_id: UUID
    is_active: bool
    is_staff: bool
    is_superuser: bool
    date_joined: datetime
    last_login: Optional[datetime]
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
