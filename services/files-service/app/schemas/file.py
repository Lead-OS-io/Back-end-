from uuid import UUID
"""
Pydantic schemas for files service
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
# =============================================================================
# FILE SCHEMAS
# =============================================================================

class FileUploadResponse(BaseModel):
    """Response after successful file upload"""
    id: UUID
    filename: str
    original_filename: str
    file_type: str
    mime_type: str
    size: int
    url: str  # Download URL


class FileInfoResponse(BaseModel):
    """Detailed file information"""
    id: UUID
    tenant_id: UUID
    filename: str
    original_filename: str
    file_path: str
    file_type: str
    mime_type: str
    extension: str
    size: int
    uploaded_by_id: UUID
    description: Optional[str]
    tags: Optional[str]
    is_public: bool
    is_active: bool
    created_at: datetime
    modified_at: datetime
    
    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    """List of files with pagination"""
    items: List[FileInfoResponse]
    total: int
    page: int
    size: int
    pages: int


class FileUpdateRequest(BaseModel):
    """Update file metadata"""
    description: Optional[str] = None
    tags: Optional[str] = None
    is_public: Optional[bool] = None



