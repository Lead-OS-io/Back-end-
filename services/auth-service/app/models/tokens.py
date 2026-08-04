"""
Refresh token and login attempt models.
"""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel


class RefreshToken(SQLModel, table=True):
    """Refresh token storage."""
    __tablename__ = "auth_refresh_tokens"

    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(index=True, foreign_key="public.users.id")
    tenant_id: uuid.UUID = Field(index=True)
    token_hash: str = Field(index=True)
    device_type: Optional[str] = Field(default=None, max_length=20)
    device_info: Optional[str] = Field(default=None, max_length=255)
    ip_address: Optional[str] = Field(default=None, max_length=45)
    is_revoked: bool = Field(default=False)
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LoginAttempt(SQLModel, table=True):
    """Track login attempts for security."""
    __tablename__ = "auth_login_attempts"

    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(index=True)
    ip_address: str = Field(max_length=45)
    success: bool = Field(default=False)
    failure_reason: Optional[str] = Field(default=None, max_length=100)
    user_agent: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)
