"""
Business logic for files service
"""
import os
import uuid
import shutil
from typing import Optional, List
from uuid import UUID
from sqlmodel import Session, or_
from datetime import datetime
from pathlib import Path

from app.models import File
from app.config import settings


class FileService:
    """Service for file operations"""
    
    @staticmethod
    def get_file_type(extension: str) -> str:
        """Determine file type based on extension"""
        extension = extension.lower().lstrip('.')
        
        if extension in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg']:
            return 'image'
        elif extension in ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt']:
            return 'document'
        elif extension in ['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv']:
            return 'video'
        else:
            return 'other'
    
    @staticmethod
    def get_storage_path(tenant_id: UUID, file_type: str, filename: str) -> tuple[str, str]:
        """
        Get storage path for a file
        Returns: (absolute_path, relative_path)
        """
        # Organize by tenant and type: storage/{tenant_id}/{file_type}/{filename}
        relative_path = os.path.join(str(tenant_id), file_type, filename)
        absolute_path = os.path.join(settings.STORAGE_PATH, relative_path)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
        
        return absolute_path, relative_path
    
    @staticmethod
    async def save_file(
        db: Session,
        file_content: bytes,
        original_filename: str,
        mime_type: str,
        tenant_id: UUID,
        uploaded_by_id: UUID,
        description: Optional[str] = None,
        tags: Optional[str] = None,
        is_public: bool = False
    ) -> File:
        """Save file to storage and create database record"""
        # Validate file size
        if len(file_content) > settings.MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds maximum allowed ({settings.MAX_FILE_SIZE} bytes)")
        
        # Extract extension
        extension = Path(original_filename).suffix.lstrip('.').lower()
        
        # Validate extension
        if extension not in settings.ALLOWED_EXTENSIONS:
            raise ValueError(f"File extension '{extension}' not allowed")
        
        # Determine file type
        file_type = FileService.get_file_type(extension)
        
        # Generate unique filename
        unique_filename = f"{uuid.uuid4()}.{extension}"
        
        # Get storage path
        absolute_path, relative_path = FileService.get_storage_path(
            tenant_id, file_type, unique_filename
        )
        
        # Save file to disk
        with open(absolute_path, 'wb') as f:
            f.write(file_content)
        
        # Create database record
        file_record = File(
            tenant_id=tenant_id,
            filename=unique_filename,
            original_filename=original_filename,
            file_path=relative_path,
            file_type=file_type,
            mime_type=mime_type,
            extension=extension,
            size=len(file_content),
            uploaded_by_id=uploaded_by_id,
            description=description,
            tags=tags,
            is_public=is_public
        )
        
        db.add(file_record)
        db.commit()
        db.refresh(file_record)
        
        return file_record
    
    @staticmethod
    def get_file(db: Session, file_id: UUID, tenant_id: UUID) -> Optional[File]:
        """Get file record by ID"""
        return db.query(File).filter(
            File.id == file_id,
            File.tenant_id == tenant_id,
            File.is_active == True
        ).first()
    
    @staticmethod
    def list_files(
        db: Session,
        tenant_id: UUID,
        file_type: Optional[str] = None,
        uploaded_by_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None
    ) -> tuple[List[File], int]:
        """List files with pagination"""
        query = db.query(File).filter(
            File.tenant_id == tenant_id,
            File.is_active == True
        )
        
        if file_type:
            query = query.filter(File.file_type == file_type)
        
        if uploaded_by_id:
            query = query.filter(File.uploaded_by_id == uploaded_by_id)
        
        if search:
            query = query.filter(
                or_(
                    File.original_filename.ilike(f"%{search}%"),
                    File.description.ilike(f"%{search}%"),
                    File.tags.ilike(f"%{search}%")
                )
            )
        
        total = query.count()
        files = query.order_by(File.created_at.desc()).offset(skip).limit(limit).all()
        
        return files, total
    
    @staticmethod
    def update_file(
        db: Session,
        file: File,
        description: Optional[str] = None,
        tags: Optional[str] = None,
        is_public: Optional[bool] = None
    ) -> File:
        """Update file metadata"""
        if description is not None:
            file.description = description
        if tags is not None:
            file.tags = tags
        if is_public is not None:
            file.is_public = is_public
        
        file.modified_at = datetime.utcnow()
        db.add(file)
        db.commit()
        db.refresh(file)
        return file
    
    @staticmethod
    def delete_file(db: Session, file: File):
        """Delete file (soft delete in DB, actual file remains)"""
        file.is_active = False
        file.modified_at = datetime.utcnow()
        db.add(file)
        db.commit()
    
    @staticmethod
    def get_absolute_path(file: File) -> str:
        """Get absolute path to file on disk"""
        return os.path.join(settings.STORAGE_PATH, file.file_path)
    
    @staticmethod
    def delete_file_from_disk(file: File):
        """Permanently delete file from disk"""
        absolute_path = FileService.get_absolute_path(file)
        if os.path.exists(absolute_path):
            os.remove(absolute_path)



