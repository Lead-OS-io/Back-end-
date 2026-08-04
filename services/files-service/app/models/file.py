"""
File models for the monolith database
"""
from datetime import datetime
from typing import Optional
import uuid

from sqlmodel import SQLModel, Field


class File(SQLModel, table=True):
    """
    File model - Classified by tenant and file type
    Supports all file types: images, documents, videos
    """
    __tablename__ = "files"
    
    # Primary key
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Tenant isolation
    tenant_id: uuid.UUID = Field(nullable=False, index=True)
    
    # File info
    filename: str = Field(max_length=255, nullable=False)
    original_filename: str = Field(max_length=255, nullable=False)
    file_path: str = Field(max_length=500, nullable=False)  # Relative path within storage
    file_type: str = Field(max_length=50, nullable=False, index=True)  # image, document, video
    mime_type: str = Field(max_length=100, nullable=False)
    extension: str = Field(max_length=20, nullable=False)
    size: int = Field(nullable=False)  # Size in bytes
    
    # Upload info
    uploaded_by_id: uuid.UUID = Field(nullable=False)
    
    # Optional metadata
    description: Optional[str] = Field(default=None, max_length=500)
    tags: Optional[str] = Field(default=None, max_length=500)  # Comma-separated tags
    
    # Access control
    is_public: bool = Field(default=False)
    
    # Status
    is_active: bool = Field(default=True, nullable=False)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    modified_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)



