"""
Event schemas for inter-service communication.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import Field
import uuid

from shared.schemas.base import BaseSchema


class EventType(str, Enum):
    """Types of events that can be published."""
    # User events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    
    # Tenant events
    TENANT_CREATED = "tenant.created"
    TENANT_UPDATED = "tenant.updated"
    TENANT_SUSPENDED = "tenant.suspended"
    TENANT_ACTIVATED = "tenant.activated"
    
    # Case events
    CASE_CREATED = "case.created"
    CASE_UPDATED = "case.updated"
    CASE_STATUS_CHANGED = "case.status_changed"
    CASE_ASSIGNED = "case.assigned"
    
    # Campaign events
    CAMPAIGN_CREATED = "campaign.created"
    CAMPAIGN_SCHEDULED = "campaign.scheduled"
    CAMPAIGN_SENT = "campaign.sent"
    CAMPAIGN_COMPLETED = "campaign.completed"
    
    # Email events
    EMAIL_SENT = "email.sent"
    EMAIL_DELIVERED = "email.delivered"
    EMAIL_OPENED = "email.opened"
    EMAIL_CLICKED = "email.clicked"
    EMAIL_BOUNCED = "email.bounced"
    EMAIL_COMPLAINED = "email.complained"
    
    # Dashboard events
    METRICS_UPDATED = "metrics.updated"


class Event(BaseSchema):
    """Base event schema for inter-service communication."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType
    tenant_id: str
    user_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True


class EmailEvent(Event):
    """Email-specific event."""
    email_id: str
    recipient: str
    subject: Optional[str] = None
    campaign_id: Optional[str] = None


class CaseEvent(Event):
    """Case-specific event."""
    case_id: int
    status: Optional[int] = None
    assigned_to: Optional[str] = None


class CampaignEvent(Event):
    """Campaign-specific event."""
    campaign_id: str
    total_recipients: Optional[int] = None
    sent_count: Optional[int] = None

