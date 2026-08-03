"""
Pydantic schemas for users service
"""
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr, Field


# =============================================================================
# USER SCHEMAS
# =============================================================================

class UserBase(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    country_code: Optional[int] = None
    mobile: Optional[str] = None
    npn: Optional[str] = None
    anpn: Optional[str] = None
    compensation: Optional[int] = None
    job_title: Optional[int] = None
    role_id: Optional[int] = None
    is_individual: Optional[bool] = None
    business_name: Optional[str] = None
    tax_number: Optional[str] = None
    fein: Optional[int] = None
    residential_address: Optional[Dict[str, Any]] = None
    mailing_address: Optional[Dict[str, Any]] = None
    business_address: Optional[Dict[str, Any]] = None
    permissions: Optional[Dict[str, Any]] = None


class UserCreate(UserBase):
    password: str
    tenant_id: UUID
    upline_id: Optional[UUID] = None
    invited_by_id: Optional[UUID] = None
    production_upline_id: Optional[UUID] = None


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    country_code: Optional[int] = None
    mobile: Optional[str] = None
    npn: Optional[str] = None
    anpn: Optional[str] = None
    compensation: Optional[int] = None
    job_title: Optional[int] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    is_staff: Optional[bool] = None
    is_superuser: Optional[bool] = None
    residential_address: Optional[Dict[str, Any]] = None
    mailing_address: Optional[Dict[str, Any]] = None
    business_address: Optional[Dict[str, Any]] = None
    permissions: Optional[Dict[str, Any]] = None
    upline_id: Optional[UUID] = None
    accepted_campaign_terms_at: Optional[datetime] = None
    opt_in_notes: Optional[str] = None
    accepted_underwriter_terms_at: Optional[datetime] = None


class UserResponse(UserBase):
    id: UUID
    tenant_id: UUID
    is_active: bool
    is_staff: bool
    is_superuser: bool
    date_joined: datetime
    last_login: Optional[datetime]
    upline_id: Optional[UUID]
    invited_by_id: Optional[UUID]
    production_upline_id: Optional[UUID]
    accepted_campaign_terms_at: Optional[datetime] = None
    accepted_underwriter_terms_at: Optional[datetime] = None
    created_at: datetime
    modified_at: datetime

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    size: int
    pages: int


# =============================================================================
# AGENT SETTINGS SCHEMAS
# =============================================================================

class AgentSettingCreate(BaseModel):
    user_id: UUID
    tenant_id: UUID
    settings: Dict[str, Any]


class AgentSettingUpdate(BaseModel):
    settings: Dict[str, Any]


class AgentSettingResponse(BaseModel):
    id: UUID
    user_id: UUID
    tenant_id: UUID
    settings: Dict[str, Any]
    created_at: datetime
    modified_at: datetime
    
    class Config:
        from_attributes = True


# =============================================================================
# USER REQUEST SCHEMAS (NEST)
# =============================================================================

class UserRequestCreate(BaseModel):
    request_type: str  # other_request, production_change, contract_change, terminations, as_earned, commission_change
    data: Dict[str, Any]
    notes: Optional[str] = None


class UserRequestUpdate(BaseModel):
    data: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    reviewed_by_id: Optional[UUID] = None


class UserRequestResponse(BaseModel):
    id: UUID
    user_id: UUID
    tenant_id: UUID
    request_type: str
    data: Dict[str, Any]
    status: str
    created_by_id: Optional[UUID]
    reviewed_by_id: Optional[UUID]
    reviewed_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    modified_at: datetime
    
    class Config:
        from_attributes = True


class UserRequestListResponse(BaseModel):
    items: List[UserRequestResponse]
    total: int
    page: int
    size: int


# =============================================================================
# CALENDAR (DESK) SCHEMAS
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



