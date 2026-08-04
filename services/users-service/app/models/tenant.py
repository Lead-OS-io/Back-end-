"""Tenant model local (denormalizado; referenciado por FKs)."""
from datetime import datetime
import uuid

from sqlmodel import Field, SQLModel


class Tenant(SQLModel, table=True):
    """
    Tenant model (referenced for FKs).
    """
    __tablename__ = "tenants"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100, index=True)
    domain: str = Field(max_length=100, unique=True, index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
