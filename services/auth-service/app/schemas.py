"""
Auth Service Pydantic Schemas.
"""
from typing import Optional, List, Any, Union, Dict
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
import uuid


# Request schemas
class LoginRequest(BaseModel):
    """Login request schema."""
    email: EmailStr
    password: str = Field(..., min_length=1)
    platform: Optional[str] = Field(
        default=None,
        description="desk | hub | nest (obligatorio para firmar con la clave correcta)",
    )


class RegisterRequest(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    tenant_id: uuid.UUID


class PasswordResetRequest(BaseModel):
    """Password reset request."""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Password reset confirmation."""
    token: str
    new_password: str = Field(..., min_length=8)


class PasswordChangeRequest(BaseModel):
    """Password change request."""
    old_password: str
    new_password: str = Field(..., min_length=8)


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str
    platform: Optional[str] = Field(
        default=None,
        description="desk | hub | nest (obligatorio si no viene en el header X-Platform)",
    )


# Response schemas
class TokenResponse(BaseModel):
    """Token response schema."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    user_id: str
    email: str
    redirect_url: Optional[str] = None


class ServiceTokenRequest(BaseModel):
    """Issue a service token bound to tenant_id."""
    tenant_id: str
    expires_minutes: int = Field(default=60 * 24, ge=5, le=60 * 24 * 30)


class ServiceTokenResponse(BaseModel):
    """Service token response."""
    token: str
    expires_in: int


class UserResponse(BaseModel):
    """User response schema."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_active: bool
    is_staff: bool
    is_superuser: bool
    role_id: Optional[int]
    date_joined: Optional[datetime]
    last_login: Optional[datetime]
    permissions: Optional[Union[List[Any], Dict[str, Any]]] = None
    first_login: bool = True
    
    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Full login response with user details."""
    access_token: str
    access: str  # Alias for compatibility
    token: str   # Alias for compatibility
    refresh: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    redirect_url: Optional[str] = None


class AdminCheckResponse(BaseModel):
    """Admin check response."""
    isAdmin: bool
    permissions: List[str] = []


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

