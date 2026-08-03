"""
Cases Service Pydantic Schemas.
"""
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr
import uuid


# Request schemas
class CaseCreateRequest(BaseModel):
    """Create case request."""
    client_first_name: Optional[str] = None
    client_last_name: Optional[str] = None
    client_email: Optional[EmailStr] = None
    client_phone: Optional[str] = None
    carrier_id: Optional[int] = None
    product_id: Optional[int] = None
    face_amount: Optional[float] = None
    premium: Optional[float] = None
    general_info: Optional[Dict[str, Any]] = None
    mortgage_info: Optional[Dict[str, Any]] = None
    client_assessment: Optional[Dict[str, Any]] = None
    financial_assessment: Optional[Dict[str, Any]] = None
    type_of_coverage: Optional[Dict[str, Any]] = None
    policy_and_banking: Optional[Dict[str, Any]] = None
    beneficiaries: Optional[Dict[str, Any]] = None
    draft_id: Optional[str] = None


class CaseUpdateRequest(BaseModel):
    """Update case request."""
    status: Optional[int] = None
    client_first_name: Optional[str] = None
    client_last_name: Optional[str] = None
    client_email: Optional[EmailStr] = None
    client_phone: Optional[str] = None
    policy_number: Optional[str] = None
    carrier_id: Optional[int] = None
    product_id: Optional[int] = None
    face_amount: Optional[float] = None
    premium: Optional[float] = None
    general_info: Optional[Dict[str, Any]] = None
    mortgage_info: Optional[Dict[str, Any]] = None
    client_assessment: Optional[Dict[str, Any]] = None
    financial_assessment: Optional[Dict[str, Any]] = None
    type_of_coverage: Optional[Dict[str, Any]] = None
    policy_and_banking: Optional[Dict[str, Any]] = None
    beneficiaries: Optional[Dict[str, Any]] = None
    color: Optional[str] = None


class CaseStatusUpdateRequest(BaseModel):
    """Update case status."""
    status: int
    carrier_status_id: Optional[int] = None
    notes: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    """Bulk delete cases."""
    case_ids: List[int]


# =============================================================================
# Drafts (auto-save)
# =============================================================================


class DraftUpsertRequest(BaseModel):
    draft_id: Optional[str] = None
    draft_data: Dict[str, Any] = Field(default_factory=dict)
    section_completion_status: Dict[str, Any] = Field(default_factory=dict)
    last_section_updated: Optional[str] = None
    is_active: bool = True


class DraftResponse(BaseModel):
    id: str
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    draft_data: Dict[str, Any]
    section_completion_status: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    version: int
    is_active: bool
    last_section_updated: Optional[str] = None

    class Config:
        from_attributes = True


# =============================================================================
# Desk: Book of Business (internal orchestration helpers)
# =============================================================================


class BoBFilterCaseIdsRequest(BaseModel):
    """
    Case-level filters that are sourced from the cases table (NOT premium_sold).
    Desk will combine these ids with premium-service policy filters.
    """

    search: Optional[str] = None
    date_from: Optional[str] = None  # YYYY-MM-DD or ISO datetime
    date_to: Optional[str] = None    # YYYY-MM-DD or ISO datetime
    policy_type: Optional[str] = None  # comma-separated, e.g. "Term,Whole Life"
    own_only: Optional[bool] = None
    user_id: Optional[str] = None


class BoBFilterCaseIdsResponse(BaseModel):
    case_ids: List[int]


class BoBQueryCasesRequest(BaseModel):
    case_ids: List[int] = Field(default_factory=list)
    page: int = Field(default=1, ge=1)
    size: int = Field(default=10, ge=1, le=100)


class BoBQueryCasesResponse(BaseModel):
    items: List["CaseDetailResponse"]
    total: int
    page: int
    size: int
    pages: int


class BoBResolveDisplayRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list)
    agency_ids: List[str] = Field(default_factory=list)
    carrier_ids: List[str] = Field(default_factory=list)
    carrier_filters: Optional[List[str]] = None
    include_carrier_names: bool = False


class BoBResolveDisplayResponse(BaseModel):
    users: Dict[str, str] = Field(default_factory=dict)
    agencies: Dict[str, str] = Field(default_factory=dict)
    carriers: Dict[str, str] = Field(default_factory=dict)
    carrier_ids_from_filters: List[str] = Field(default_factory=list)
    carrier_names: List[str] = Field(default_factory=list)


class BoBArchiveCaseResponse(BaseModel):
    archived: bool


class DraftBulkDeleteRequest(BaseModel):
    draft_ids: List[str]


# =============================================================================
# Case history
# =============================================================================


class CaseHistoryCreateRequest(BaseModel):
    history_type: str = Field(default="~", min_length=1, max_length=1)
    history_change_reason: Optional[str] = Field(default=None, max_length=100)


class CaseHistoryResponse(BaseModel):
    id: int
    history_id: int
    history_date: datetime
    history_type: str
    history_change_reason: Optional[str] = None
    history_user_id: Optional[uuid.UUID] = None

    class Config:
        from_attributes = True


# Response schemas
class CaseResponse(BaseModel):
    """Case response."""
    id: int
    tenant_id: uuid.UUID
    agent_id: Optional[uuid.UUID]
    status: Union[int, str]
    carrier_status_id: Optional[int]
    client_first_name: Optional[str]
    client_last_name: Optional[str]
    client_email: Optional[str]
    client_phone: Optional[str]
    policy_number: Optional[str]
    carrier_id: Optional[int]
    product_id: Optional[int]
    face_amount: Optional[float]
    premium: Optional[float]
    color: Optional[str]
    created_at: Optional[datetime]
    modified_at: Optional[datetime]
    submitted_at: Optional[datetime]
    issued_at: Optional[datetime]

    # -------------------------------------------------------------------------
    # Legacy Desk parity fields (needed by Desk Book of Business)
    # -------------------------------------------------------------------------
    name: Optional[str] = None
    is_active: Optional[bool] = None
    created_by_id: Optional[uuid.UUID] = None
    client1_name: Optional[str] = None
    client2_name: Optional[str] = None
    client1_email: Optional[str] = None
    client2_email: Optional[str] = None
    
    # Dashboard/Notifications compatibility fields
    type: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    time: Optional[str] = None
    actions: Optional[Union[bool, List[Dict[str, Any]]]] = None

    class Config:
        from_attributes = True


class CaseDetailResponse(CaseResponse):
    """Case detail with all JSON fields."""
    general_info: Optional[Dict[str, Any]]
    mortgage_info: Optional[Dict[str, Any]]
    client_assessment: Optional[Dict[str, Any]]
    financial_assessment: Optional[Dict[str, Any]]
    type_of_coverage: Optional[Dict[str, Any]]
    policy_and_banking: Optional[Dict[str, Any]]
    beneficiaries: Optional[Dict[str, Any]]
    # Legacy JSON fields (still used by Desk)
    general_information: Optional[Dict[str, Any]] = None
    common_details: Optional[Dict[str, Any]] = None
    benificiaries: Optional[Dict[str, Any]] = None


class CaseListResponse(BaseModel):
    """Paginated case list."""
    items: List[CaseResponse]
    total: int
    page: int
    page_size: int
    pages: int


class CaseStatsResponse(BaseModel):
    """Case statistics."""
    total: int
    by_status: Dict[str, int]
    by_carrier: Dict[str, int]
    this_month: int
    last_month: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# Medical reference (Desk case forms)
# =============================================================================


class MedicalCategoryResponse(BaseModel):
    id: int
    title: str
    is_active: bool = True
    category: Optional[str] = None
    severity_level: Optional[int] = None
    requires_date: Optional[bool] = None
    underwriting_impact: Optional[str] = None
    description: Optional[str] = None
    synonyms: Optional[List[str]] = None

    class Config:
        from_attributes = True


class MedicationResponse(BaseModel):
    id: int
    title: str
    is_active: bool = True
    category_id: Optional[int] = None
    brand_names: Optional[List[str]] = None
    medication_category: Optional[str] = None
    related_conditions: Optional[List[int]] = None
    underwriting_notes: Optional[str] = None

    class Config:
        from_attributes = True


class MedicalDataResponse(BaseModel):
    categories: List[MedicalCategoryResponse] = Field(default_factory=list)
    medications: List[MedicationResponse] = Field(default_factory=list)
    total_categories: int = 0
    total_medications: int = 0

