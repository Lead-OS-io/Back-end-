"""User schemas."""
from typing import Any, List, Optional, Union, Dict
from datetime import datetime
import uuid

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    """Registro de usuario (NUEVO flujo event-driven)."""
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    """User response schema."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_active: bool
    is_staff: bool
    is_superuser: bool
    role_id: Optional[int]
    date_joined: Optional[datetime]
    last_login: Optional[datetime]
    permissions: Optional[Union[List[Any], Dict[str, Any]]] = None
    first_login: bool = True

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Full login response with user details."""
    access_token: str
    access: str  # Alias for compatibility
    token: str   # Alias for compatibility
    refresh: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    redirect_url: Optional[str] = None
