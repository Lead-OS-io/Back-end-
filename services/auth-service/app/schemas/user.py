from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)


class UserResponse(BaseModel):
    user_id: str
    tenant_id: Optional[str]
    email: EmailStr
    full_name: Optional[str]
    phone: Optional[str]
    status: str
    has_avatar: bool
    avatar_url: Optional[str]
    created_at: str
    modified_at: str


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
