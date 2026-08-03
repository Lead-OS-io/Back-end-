"""
Base schemas shared across all services.
"""
from typing import Generic, TypeVar, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid

T = TypeVar("T")


class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    
    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            uuid.UUID: str,
        }


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response."""
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int
    
    @classmethod
    def create(cls, items: List[T], total: int, page: int, page_size: int):
        pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
    error_code: Optional[str] = None
    field_errors: Optional[dict] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None


class HealthCheck(BaseModel):
    """Health check response."""
    status: str = "healthy"
    service: str
    version: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    dependencies: Optional[dict] = None


class ServiceInfo(BaseModel):
    """Service information for discovery."""
    name: str
    version: str
    base_url: str
    health_url: str
    endpoints: List[str] = []

