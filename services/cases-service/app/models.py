"""
Cases Service Models.
References the shared database tables.
"""
from datetime import datetime, date as dt_date, timedelta
from typing import Optional, Dict, Any
from enum import Enum
import uuid
from sqlalchemy import Column, BigInteger, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel, JSON


class CaseStatus(int, Enum):
    """Case status codes."""
    DRAFT = 0
    SUBMITTED = 1
    IN_REVIEW = 2
    APPROVED = 3
    ISSUED = 4
    DECLINED = 5
    CANCELLED = 6


class CaseData(SQLModel, table=True):
    """
    Case data model.
    Maps to public.cases in the shared database.
    """
    __tablename__ = "cases"
    __table_args__ = {"schema": "public"}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    
    # Agent relationship
    agent_id: Optional[uuid.UUID] = Field(default=None, index=True)
    
    # Status
    status: int = Field(default=0, index=True)
    carrier_status_id: Optional[int] = Field(default=None, index=True)
    
    # Client info
    client_first_name: Optional[str] = Field(default=None, max_length=100)
    client_last_name: Optional[str] = Field(default=None, max_length=100)
    client_email: Optional[str] = Field(default=None, max_length=255)
    client_phone: Optional[str] = Field(default=None, max_length=50)
    
    # Policy info
    policy_number: Optional[str] = Field(default=None, max_length=100, index=True)
    carrier_id: Optional[int] = Field(default=None, index=True)
    product_id: Optional[int] = Field(default=None, index=True)
    
    # Premium
    face_amount: Optional[float] = Field(default=None)
    premium: Optional[float] = Field(default=None)
    
    # JSON data fields
    # Note: avoid importing SQLAlchemy JSON/JSONB; SQLModel maps dict appropriately.
    general_info: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    mortgage_info: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    client_assessment: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    financial_assessment: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    type_of_coverage: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    policy_and_banking: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)
    beneficiaries: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)

    # Paridad con legacy (columnas copiadas desde data_access_casedata)
    name: Optional[str] = Field(default=None, max_length=255)
    date: Optional[dt_date] = Field(default=None)
    general_information: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)  # jsonb en DB
    benificiaries: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)  # jsonb en DB (typo legacy)
    common_details: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)  # jsonb en DB
    is_active: Optional[bool] = Field(default=None, index=True)
    created_by_id: Optional[uuid.UUID] = Field(default=None, index=True)
    is_completed: Optional[bool] = Field(default=None)
    approved_policy_doc: Optional[str] = Field(default=None, max_length=255)
    policy_approval_confirmation_send: Optional[bool] = Field(default=None)
    policy_doc: Optional[str] = Field(default=None, max_length=255)
    policy_submit_confirmation_send: Optional[bool] = Field(default=None)
    tag: Optional[uuid.UUID] = Field(default=None)
    client1_dob: Optional[datetime] = Field(default=None)
    client1_email: Optional[str] = Field(default=None, max_length=255)
    client1_name: Optional[str] = Field(default=None, max_length=255)
    client2_dob: Optional[datetime] = Field(default=None)
    client2_email: Optional[str] = Field(default=None, max_length=255)
    client2_name: Optional[str] = Field(default=None, max_length=255)
    have_two_clients: Optional[bool] = Field(default=None)
    
    # Color/priority
    color: Optional[str] = Field(default=None, max_length=20)
    
    # Timestamps
    created_at: Optional[datetime] = Field(default=None, index=True)
    modified_at: Optional[datetime] = Field(default=None)
    submitted_at: Optional[datetime] = Field(default=None)
    issued_at: Optional[datetime] = Field(default=None)
    
    class Config:
        from_attributes = True


# =============================================================================
# Medical reference tables (used by Desk case forms)
# Source of truth must be cases-service.
# =============================================================================


class MedicationCategory(SQLModel, table=True):
    __tablename__ = "medication_categories"
    __table_args__ = {"schema": "public"}

    id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    created_at: Optional[datetime] = Field(default=None)
    modified_at: Optional[datetime] = Field(default=None)

    title: str = Field(max_length=255, index=True)
    is_active: bool = Field(default=True, index=True)

    category: Optional[str] = Field(default=None, max_length=100, index=True)
    severity_level: Optional[int] = Field(default=None)
    requires_date: Optional[bool] = Field(default=False)
    underwriting_impact: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None)
    synonyms: Optional[list[str]] = Field(default=None, sa_column=Column(ARRAY(String)))

    created_by_id: Optional[uuid.UUID] = Field(default=None, index=True)
    modified_by_id: Optional[uuid.UUID] = Field(default=None, index=True)


class Medication(SQLModel, table=True):
    __tablename__ = "medications"
    __table_args__ = {"schema": "public"}

    id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    created_at: Optional[datetime] = Field(default=None)
    modified_at: Optional[datetime] = Field(default=None)

    title: str = Field(max_length=255, index=True)
    is_active: bool = Field(default=True, index=True)

    category_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, index=True))
    brand_names: Optional[list[str]] = Field(default=None, sa_column=Column(ARRAY(String)))
    medication_category: Optional[str] = Field(default=None, max_length=100, index=True)
    related_conditions: Optional[list[int]] = Field(default=None, sa_column=Column(ARRAY(Integer)))
    underwriting_notes: Optional[str] = Field(default=None)

    created_by_id: Optional[uuid.UUID] = Field(default=None, index=True)
    modified_by_id: Optional[uuid.UUID] = Field(default=None, index=True)


class EmailHistory(SQLModel, table=True):
    """Email history for cases."""
    __tablename__ = "case_email_history"
    __table_args__ = {"schema": "public"}
    
    id: Optional[int] = Field(default=None, primary_key=True)
    case_id: int = Field(index=True)
    tenant_id: uuid.UUID = Field(index=True)
    
    email_type: str = Field(max_length=50)
    recipient: str = Field(max_length=255)
    subject: str = Field(max_length=500)
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="sent", max_length=20)
    
    class Config:
        from_attributes = True


class Draft(SQLModel, table=True):
    """
    Case drafts (auto-save).
    Source of truth: public.drafts (shared DB).
    """

    __tablename__ = "drafts"
    __table_args__ = {"schema": "public"}

    id: str = Field(primary_key=True, default_factory=lambda: str(uuid.uuid4()))
    tenant_id: uuid.UUID = Field(index=True)
    user_id: uuid.UUID = Field(index=True)

    draft_data: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    section_completion_status: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(days=30))

    version: int = Field(default=1)
    is_active: bool = Field(default=True, index=True)
    last_section_updated: Optional[str] = Field(default=None)

    def bump(self, *, last_section_updated: Optional[str] = None) -> None:
        self.updated_at = datetime.utcnow()
        self.expires_at = datetime.utcnow() + timedelta(days=30)
        self.version = int(self.version or 0) + 1
        if last_section_updated is not None:
            self.last_section_updated = last_section_updated


class CaseHistory(SQLModel, table=True):
    """
    Case history (formerly `public.data_access_historicalcasedata`).
    Source of truth: public.cases_history via cases-service.
    """

    __tablename__ = "cases_history"
    __table_args__ = {"schema": "public"}

    # Original case id (from the main cases table)
    id: int = Field(index=True)

    # History PK
    history_id: Optional[int] = Field(default=None, primary_key=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    modified_at: datetime = Field(default_factory=datetime.utcnow)

    name: Optional[str] = Field(default=None, max_length=255)
    date: dt_date = Field(default_factory=dt_date.today)

    mortgage_info: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    client_assessment: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    financial_assessment: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    type_of_coverage: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    general_information: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    policy_and_banking: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    benificiaries: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    common_details: Dict[str, Any] = Field(default_factory=dict, sa_type=JSON)

    status: int = Field(default=0)
    is_active: bool = Field(default=True)

    history_date: datetime = Field(default_factory=datetime.utcnow, index=True)
    history_change_reason: Optional[str] = Field(default=None, max_length=100)
    history_type: str = Field(default="~", max_length=1)

    created_by_id: Optional[uuid.UUID] = Field(default=None, index=True)
    history_user_id: Optional[uuid.UUID] = Field(default=None, index=True)

    is_completed: bool = Field(default=False)
    approved_policy_doc: Optional[str] = Field(default=None, max_length=255)
    policy_approval_confirmation_send: bool = Field(default=False)
    policy_doc: Optional[str] = Field(default=None, max_length=255)
    policy_number: Optional[str] = Field(default=None, max_length=255)
    policy_submit_confirmation_send: bool = Field(default=False)
    tag: Optional[uuid.UUID] = Field(default=None)

    client1_dob: Optional[datetime] = Field(default=None)
    client1_email: Optional[str] = Field(default=None, max_length=255)
    client1_name: Optional[str] = Field(default=None, max_length=255)
    client2_dob: Optional[datetime] = Field(default=None)
    client2_email: Optional[str] = Field(default=None, max_length=255)
    client2_name: Optional[str] = Field(default=None, max_length=255)
    have_two_clients: bool = Field(default=False)

class UserRow(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(primary_key=True)
    tenant_id: uuid.UUID = Field(index=True)
    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    npn: Optional[str] = Field(default=None, max_length=255)
    is_superuser: bool = Field(default=False)
    access_id: Optional[uuid.UUID] = Field(default=None, description="Arialeads access UUID")





class AgencyRow(SQLModel, table=True):
    __tablename__ = "agencies"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(primary_key=True)
    name: Optional[str] = Field(default=None)


class PremiumSoldRow(SQLModel, table=True):
    __tablename__ = "premium_sold"
    __table_args__ = {"schema": "public"}

    id: int = Field(primary_key=True)
    created_at: Optional[datetime] = Field(default=None)
    modified_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True, index=True)
    policy_number: Optional[str] = Field(default=None, max_length=255, index=True)
    unique_policy_identifier: Optional[str] = Field(default=None, max_length=255, index=True)
    annual_premium: Optional[float] = Field(default=None)
    status: int = Field(default=0, index=True)
    carrier_status_id: Optional[int] = Field(default=None, index=True)
    effective_date: Optional[datetime] = Field(default=None, index=True)
    laps_date: Optional[datetime] = Field(default=None, index=True)
    is_lapsed: Optional[bool] = Field(default=None, index=True)
    is_pending_lapsed: Optional[bool] = Field(default=None, index=True)
    agency_id: Optional[uuid.UUID] = Field(default=None, index=True)
    carrier_id: Optional[uuid.UUID] = Field(default=None, index=True)
    product_id: Optional[uuid.UUID] = Field(default=None, index=True)
    case_data_id: Optional[int] = Field(default=None, index=True)
    user_id: uuid.UUID = Field(index=True)


class CarrierRow(SQLModel, table=True):
    __tablename__ = "carriers"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(primary_key=True)
    name: Optional[str] = Field(default=None)
    display_name_override: Optional[str] = Field(default=None)


class ProductRow(SQLModel, table=True):
    __tablename__ = "products"
    __table_args__ = {"schema": "public"}

    id: uuid.UUID = Field(primary_key=True)
    name: Optional[str] = Field(default=None)
    product_type: int = Field(default=0)
    carrier_id: Optional[uuid.UUID] = Field(default=None, index=True)
