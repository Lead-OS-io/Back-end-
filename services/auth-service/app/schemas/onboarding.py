from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import UserStatus


class OnboardingRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    business_name: str = Field(min_length=1, max_length=255)
    timezone: str = Field(min_length=1, max_length=64)
    legal_name: str = Field(min_length=1, max_length=255)
    support_inbox: str = Field(min_length=1, max_length=255)


class OnboardingAcceptedResponse(BaseModel):
    user_id: UUID
    status: UserStatus = UserStatus.PENDING_TENANT
