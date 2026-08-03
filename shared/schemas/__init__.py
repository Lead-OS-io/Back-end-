"""
Shared Pydantic schemas for inter-service communication.
"""
from shared.schemas.base import BaseSchema, PaginatedResponse, ErrorResponse
from shared.schemas.tenant import TenantSchema, TenantCreate, TenantInDB
from shared.schemas.user import UserSchema, UserCreate, UserInDB, TokenPayload
from shared.schemas.events import Event, EventType

__all__ = [
    "BaseSchema",
    "PaginatedResponse", 
    "ErrorResponse",
    "TenantSchema",
    "TenantCreate",
    "TenantInDB",
    "UserSchema",
    "UserCreate",
    "UserInDB",
    "TokenPayload",
    "Event",
    "EventType",
]

