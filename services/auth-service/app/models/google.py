"""
Google OAuth token model.
"""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel


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
