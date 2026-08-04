"""Aria webhook schemas (payload de Aria + helpers)."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class AriaUserPayload(BaseModel):
    id: Optional[int] = None
    email: EmailStr
    name: Optional[str] = None


class AriaProductPayload(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None


class AriaAccessPayload(BaseModel):
    id: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class AriaSubscriptionPayload(BaseModel):
    id: Optional[str] = None
    status: Optional[str] = None
    billing_interval: Optional[str] = None
    next_payment: Optional[datetime] = None
    amount: Optional[float] = None
    is_active: Optional[bool] = None


class AriaWebhookPayload(BaseModel):
    event_type: str
    timestamp: datetime
    user: AriaUserPayload
    product: Optional[AriaProductPayload] = None
    access_id: Optional[str] = None
    access: Optional[AriaAccessPayload] = None
    subscription: Optional[AriaSubscriptionPayload] = None
    subscription_id: Optional[str] = None
