"""
User model for authentication.
Source of truth for email/password en el monolito.
"""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """
    User model for authentication.
    Source of truth for email/password en el monolito.
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
