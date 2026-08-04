"""
Pydantic schemas for users service
"""
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr, Field
# =============================================================================

class UserRequestCreate(BaseModel):
    request_type: str  # tipo libre, definido por el dominio consumidor
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
