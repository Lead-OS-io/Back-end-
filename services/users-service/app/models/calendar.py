"""CalendarEvent model (Desk)."""
from datetime import datetime
from typing import Optional, List
import uuid

from sqlmodel import Field, SQLModel, JSON, Column, Text


class CalendarEvent(SQLModel, table=True):
    """
    Calendar events and reminders (Desk).

    NOTE: This service is the only one that should read/write this table.
    """

    __tablename__ = "calendar"

    id: Optional[int] = Field(default=None, primary_key=True)

    tenant_id: Optional[uuid.UUID] = Field(default=None, foreign_key="tenants.id", index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    modified_at: datetime = Field(default_factory=datetime.utcnow)

    title: str = Field(max_length=255, index=True)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    event_type: str = Field(max_length=50, index=True)

    start_date: datetime = Field(index=True)
    end_date: datetime = Field(index=True)
    all_day: bool = Field(default=False)
    timezone: str = Field(default="America/New_York", max_length=50)

    location: Optional[str] = Field(default=None, max_length=255)
    color: str = Field(default="#465fff", max_length=7)
    priority: str = Field(default="medium", max_length=20)
    status: str = Field(default="scheduled", max_length=20)
    is_active: bool = Field(default=True)

    owner_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_by_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    assigned_to_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id", index=True)

    case_data_id: Optional[int] = Field(default=None, index=True)
    policy_id: Optional[int] = Field(default=None, index=True)
    agency_id: Optional[uuid.UUID] = Field(default=None, index=True)

    reminder_before_minutes: int = Field(default=15)
    reminder_sent: bool = Field(default=False)
    reminder_sent_at: Optional[datetime] = Field(default=None)

    visibility: str = Field(default="private", max_length=20)
    shared_with: Optional[List[str]] = Field(default=[], sa_column=Column(JSON))

    google_calendar_id: Optional[str] = Field(default=None, max_length=255)
    google_calendar_synced: bool = Field(default=False)
    google_calendar_synced_at: Optional[datetime] = Field(default=None)
    meet_url: Optional[str] = Field(default=None, max_length=500)
