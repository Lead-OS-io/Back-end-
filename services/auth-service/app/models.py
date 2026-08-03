"""
Auth Service Models.
Uses the shared database but with auth schema.
"""
from datetime import datetime
from typing import Optional
import uuid
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """
    User model for authentication.
    Source of truth for email/password in el monolito.
    """
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}  # siempre en public
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    
    # Authentication
    email: str = Field(unique=True, index=True, nullable=False, max_length=255)
    password: Optional[str] = Field(default=None, nullable=True)  # bcrypt (opcionalmente cifrado con Fernet)

    is_active: bool = Field(default=True, nullable=False)
    is_staff: bool = Field(default=False, nullable=False)
    is_superuser: bool = Field(default=False, nullable=False)
    
    # Profile
    first_name: Optional[str] = Field(default=None, max_length=150)
    last_name: Optional[str] = Field(default=None, max_length=150)
    
    # Role
    role_id: Optional[int] = Field(default=None, index=True)
    
    # Timestamps
    date_joined: Optional[datetime] = Field(default=None)
    last_login: Optional[datetime] = Field(default=None)
    created_at: Optional[datetime] = Field(default=None)
    modified_at: Optional[datetime] = Field(default=None)
    
    # Password recovery
    password_recovery_token: Optional[str] = Field(default=None)
    
    first_login: bool = Field(default=True, nullable=False)

    class Config:
        from_attributes = True


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


class GoogleOAuthToken(SQLModel, table=True):
    """
    Stores Google OAuth refresh token per (tenant_id, user_id).

    OAuth lives in auth-service. Other services (mailing/users) ask auth-service
    for short-lived Google access tokens.
    """
    __tablename__ = "google_oauth_tokens"
    __table_args__ = {"schema": "public"}

    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    user_id: uuid.UUID = Field(index=True, foreign_key="public.users.id")

    google_account_email: Optional[str] = Field(default=None, max_length=255)
    # Stored encrypted using auth-service Fernet utilities.
    refresh_token: str = Field(nullable=False)

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

