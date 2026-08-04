"""Auth schemas (requests/responses del contrato API)."""
from typing import Any, List, Optional, Union, Dict
from datetime import datetime
import uuid

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Login request schema."""
    email: EmailStr
    password: str = Field(..., min_length=1)


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str


class RefreshRequest(RefreshTokenRequest):
    pass


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


class TokenValidateRequest(BaseModel):
    token: str


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str


class AdminCheckResponse(BaseModel):
    """Admin check response."""
    isAdmin: bool
    permissions: List[str] = []


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
