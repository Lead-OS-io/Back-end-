from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import UserStatus


class OnboardingRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    business_name: str = Field(min_length=1, max_length=255)
    timezone: str = Field(min_length=1, max_length=64)
    legal_name: str = Field(min_length=1, max_length=255)
    support_inbox: EmailStr

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            parsed = phonenumbers.parse(value, None)
        except phonenumbers.NumberParseException as exc:
            raise ValueError("phone must be a valid E.164 international number") from exc
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("phone must be a valid E.164 international number")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA identifier") from exc
        return value


class OnboardingAcceptedResponse(BaseModel):
    user_id: UUID
    status: UserStatus = UserStatus.PENDING_TENANT
