"""
Pydantic schemas for users service
"""
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr, Field

# =============================================================================

class CalendarBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    event_type: str

    start_date: datetime
    end_date: datetime
    all_day: bool = False
    timezone: str = "America/New_York"

    location: Optional[str] = None
    color: str = "#465fff"
    priority: str = "medium"
    status: str = "scheduled"

    assigned_to_id: Optional[UUID] = None
    case_data_id: Optional[int] = None
    policy_id: Optional[int] = None
    agency_id: Optional[UUID] = None

    reminder_before_minutes: int = 15
    visibility: str = "private"
    shared_with: List[str] = Field(default_factory=list)


class CalendarCreate(CalendarBase):
    pass


class CalendarUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    event_type: Optional[str] = None

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    all_day: Optional[bool] = None
    timezone: Optional[str] = None

    location: Optional[str] = None
    color: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None

    assigned_to_id: Optional[UUID] = None
    case_data_id: Optional[int] = None
    policy_id: Optional[int] = None
    agency_id: Optional[UUID] = None

    reminder_before_minutes: Optional[int] = None
    visibility: Optional[str] = None
    shared_with: Optional[List[str]] = None


class CalendarResponse(CalendarBase):
    id: int
    tenant_id: Optional[UUID] = None
    owner_id: UUID
    created_by_id: UUID
    is_active: bool
    reminder_sent: bool
    reminder_sent_at: Optional[datetime]
    google_calendar_id: Optional[str] = None
    google_calendar_synced: bool
    google_calendar_synced_at: Optional[datetime]
    meet_url: Optional[str] = None
    created_at: datetime
    modified_at: datetime

    class Config:
        from_attributes = True


class CalendarReminderItem(BaseModel):
    id: int
    type: str = "reminder"
    title: str
    description: Optional[str] = None
    time: str
    status: str
    actions: bool = True
    event_type: str
    start_date: datetime
    end_date: datetime
    location: Optional[str] = None
    case_data_id: Optional[int] = None
    policy_id: Optional[int] = None


class PolicyAlertForCalendar(BaseModel):
    id: int
    name: Optional[str] = None
    policy_number: Optional[str] = None
    date: Optional[str] = None  # MM-DD-YYYY from premium-service


class PolicyWarningSyncRequest(BaseModel):
    alerts: List[PolicyAlertForCalendar] = Field(default_factory=list)


class PolicyWarningSyncResponse(BaseModel):
    created: int
