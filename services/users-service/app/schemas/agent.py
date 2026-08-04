"""
Pydantic schemas for users service
"""
from datetime import datetime
from uuid import UUID
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, EmailStr, Field

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
