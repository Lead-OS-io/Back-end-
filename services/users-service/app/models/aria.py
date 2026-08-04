"""Aria webhook dedupe y estado de suscripción (usuarios de Aria)."""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import Field, SQLModel, JSON


class AriaWebhookEvent(SQLModel, table=True):
    """Dedupe de eventos Aria (ON CONFLICT event_key)."""
    __tablename__ = "aria_webhook_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    event_key: str = Field(max_length=64, unique=True, index=True)
    event_type: str = Field(max_length=50, index=True)
    access_id: Optional[str] = Field(default=None, max_length=100)
    user_email: str = Field(max_length=255, index=True)
    payload: dict = Field(default_factory=dict, sa_type=JSON)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AriaSubscriptionState(SQLModel, table=True):
    """Estado de suscripción por (tenant_id, user_email)."""
    __tablename__ = "aria_subscription_states"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    user_id: Optional[uuid.UUID] = Field(default=None, index=True)
    user_email: str = Field(max_length=255, index=True)
    access_id: Optional[str] = Field(default=None, max_length=100)
    subscription_id: Optional[str] = Field(default=None, max_length=100)
    access_status: Optional[str] = Field(default=None, max_length=50)
    subscription_status: Optional[str] = Field(default=None, max_length=50)
    subscription_is_active: Optional[bool] = Field(default=None)
    next_payment: Optional[datetime] = Field(default=None)
    last_event_type: Optional[str] = Field(default=None, max_length=50)
    last_event_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
