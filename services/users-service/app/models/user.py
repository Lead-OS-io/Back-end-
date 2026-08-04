"""User and UserRequest models."""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel, JSON


class User(SQLModel, table=True):
    """User model: credenciales mínimas + perfil base multi-tenant."""

    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    # Tenant isolation (sin FK: la tabla tenants pertenece a tenant-service)
    tenant_id: uuid.UUID = Field(nullable=False, index=True)

    # Authentication
    email: str = Field(max_length=255, unique=True, nullable=False, index=True)
    password: str = Field(nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    is_staff: bool = Field(default=False, nullable=False)
    is_superuser: bool = Field(default=False, nullable=False)

    # Basic info
    first_name: Optional[str] = Field(default=None, max_length=150)
    last_name: Optional[str] = Field(default=None, max_length=150)
    date_joined: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = Field(default=None)

    # Roles and permissions
    role_id: Optional[int] = Field(default=None)
    permissions: Optional[dict] = Field(default=None, sa_type=JSON)

    first_login: bool = Field(default=True, nullable=False)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class UserRequest(SQLModel, table=True):
    """Generic user requests: un tipo libre + payload JSON + estado."""

    __tablename__ = "user_requests"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, index=True)
    tenant_id: uuid.UUID = Field(nullable=False, index=True)

    # Request type
    request_type: str = Field(max_length=50, nullable=False, index=True)

    # Request data (flexible JSON)
    data: dict = Field(default_factory=dict, nullable=False, sa_type=JSON)

    # Status
    status: str = Field(default="pending", max_length=50, nullable=False)

    # Metadata
    created_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    reviewed_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = Field(default=None)
    notes: Optional[str] = Field(default=None, max_length=1000)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
