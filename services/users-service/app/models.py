"""
User models for the monolith database
"""
from datetime import datetime
from typing import Optional, List
import uuid

from sqlmodel import SQLModel, Field, JSON, Column, Text


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

class User(SQLModel, table=True):
    """
    Unified user model for Desk, Hub, and Nest.
    Stores all shared user data across systems.
    """
    __tablename__ = "users"
    
    # Primary key
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Tenant isolation
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", nullable=False, index=True)
    
    # Authentication
    email: str = Field(max_length=255, unique=True, nullable=False, index=True)
    password: str = Field(nullable=False)  # Can store 3 hashes: desk, hub, nest
    is_active: bool = Field(default=True, nullable=False)
    is_staff: bool = Field(default=False, nullable=False)
    is_superuser: bool = Field(default=False, nullable=False)
    
    # Basic info
    first_name: Optional[str] = Field(default=None, max_length=150)
    last_name: Optional[str] = Field(default=None, max_length=150)
    middle_name: Optional[str] = Field(default=None, max_length=100)
    date_joined: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = Field(default=None)
    
    # Contact
    country_code: Optional[int] = Field(default=None)
    mobile: Optional[str] = Field(default=None, max_length=50)
    avatar: Optional[str] = Field(default=None, sa_column=Column(Text))
    residential_address: Optional[dict] = Field(default=None, sa_type=JSON)
    mailing_address: Optional[dict] = Field(default=None, sa_type=JSON)
    business_address: Optional[dict] = Field(default=None, sa_type=JSON)
    
    # Business/Compliance
    npn: Optional[str] = Field(default=None, max_length=255)
    anpn: Optional[str] = Field(default=None, max_length=255)
    compensation: Optional[int] = Field(default=None)
    job_title: Optional[int] = Field(default=None)
    is_contact_person: Optional[bool] = Field(default=None)
    is_individual: Optional[bool] = Field(default=None)
    business_name: Optional[str] = Field(default=None, max_length=100)
    is_ssn: Optional[bool] = Field(default=None)
    tax_number: Optional[str] = Field(default=None, max_length=15)
    fein: Optional[int] = Field(default=None)
    
    # Hierarchies (self-references)
    invited_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    production_upline_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    upline_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    
    # Arialeads Integration
    subscription_id: Optional[uuid.UUID] = Field(default=None, description="Arialeads Subscription ID")
    access_id: Optional[uuid.UUID] = Field(default=None, description="Arialeads Access ID")
    
    # External References
    imo: Optional[str] = Field(default=None, max_length=255)
    agency: Optional[str] = Field(default=None, max_length=255)
    # Map 'upline' column to upline_text to avoid conflict with potential relationships
    upline_text: Optional[str] = Field(default=None, sa_column=Column("upline", Text))
    
    # Roles and permissions
    role_id: Optional[int] = Field(default=None)
    permissions: Optional[dict] = Field(default=None, sa_type=JSON)  # JSONB: {"desk": {...}, "hub": {...}, "nest": {...}}
    
    # Campaigns consent (opt-in for email campaigns)
    accepted_campaign_terms_at: Optional[datetime] = Field(default=None)
    # AI Underwriter (Wizard Chat) disclaimer acceptance
    accepted_underwriter_terms_at: Optional[datetime] = Field(default=None)
    first_login: bool = Field(default=True, nullable=False)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class AgentSetting(SQLModel, table=True):
    """
    Agent-specific settings (primarily for Nest)
    """
    __tablename__ = "agent_settings"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, index=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", nullable=False, index=True)
    
    # Settings
    settings: dict = Field(default_factory=dict, nullable=False, sa_type=JSON)  # Flexible JSON for various settings
    
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class UserRequest(SQLModel, table=True):
    """
    Generic user requests (Nest): other_request, production_change, 
    contract_change, terminations, as_earned, commission_change
    """
    __tablename__ = "user_requests"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False, index=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", nullable=False, index=True)
    
    # Request type
    request_type: str = Field(max_length=50, nullable=False, index=True)  # other_request, production_change, etc.
    
    # Request data (flexible JSON)
    data: dict = Field(default_factory=dict, nullable=False, sa_type=JSON)
    
    # Status
    status: str = Field(default="pending", max_length=50, nullable=False)  # pending, approved, rejected, completed
    
    # Metadata
    created_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    reviewed_by_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    reviewed_at: Optional[datetime] = Field(default=None)
    notes: Optional[str] = Field(default=None)
    
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


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

