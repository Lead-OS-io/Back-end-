"""
User schemas shared across services.
"""
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from pydantic import Field, EmailStr
import uuid

from shared.schemas.base import BaseSchema


class UserBase(BaseSchema):
    """Base user schema."""
    email: EmailStr
    first_name: Optional[str] = Field(None, max_length=150)
    last_name: Optional[str] = Field(None, max_length=150)
    is_active: bool = True


class UserCreate(UserBase):
    """Schema for creating a user."""
    password: str = Field(..., min_length=8)
    tenant_id: uuid.UUID
    role_id: Optional[int] = None


class UserUpdate(BaseSchema):
    """Schema for updating a user."""
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: Optional[bool] = None
    role_id: Optional[int] = None


class UserSchema(UserBase):
    """Full user schema for responses."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    role_id: Optional[int] = None
    is_staff: bool = False
    is_superuser: bool = False
    date_joined: Optional[datetime] = None
    last_login: Optional[datetime] = None
    
    @property
    def full_name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.last_name or str(self.email)


class UserInDB(UserSchema):
    """User schema with password hash (internal use only)."""
    password: str
    encrypted_password: Optional[str] = None


class TokenPayload(BaseSchema):
    """JWT token payload."""
    sub: str  # User ID
    tenant_id: str
    email: str
    role_id: Optional[int] = None
    is_staff: bool = False
    is_superuser: bool = False
    exp: datetime
    iat: datetime
    
    @property
    def user_id(self) -> str:
        return self.sub


class TokenResponse(BaseSchema):
    """Token response schema."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None


class UserContext(BaseSchema):
    """Minimal user context passed between services."""
    id: str
    tenant_id: str
    email: str
    role_id: Optional[int] = None
    is_staff: bool = False
    is_superuser: bool = False
    permissions: Union[List[str], Dict[str, Any]] = Field(default_factory=list)

