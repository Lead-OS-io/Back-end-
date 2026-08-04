"""
Files business logic (metadata DB). Todo query filtra por tenant_id explícito
(RLS eliminado). El disco vive en app/services/storage.py.
"""
from typing import Optional, List
from uuid import UUID
from sqlmodel import Session, or_
from datetime import datetime

from app.models import File
from app.schemas.file import FileUpdateRequest
from app.services import storage


def save_file(*, db: Session, settings, file_content: bytes, original_filename: str,
              mime_type: str, tenant_id, uploaded_by_id,
              description: Optional[str] = None, tags: Optional[str] = None,
              is_public: bool = False) -> File:
    """Guarda en disco y crea la metadata (si la metadata falla, borra el archivo)."""
    absolute_path, relative_path, unique_filename, file_type, size = storage.save_stream(
        settings=settings, file_content=file_content, original_filename=original_filename,
        mime_type=mime_type, tenant_id=tenant_id)

    try:
        file_record = File(
            tenant_id=tenant_id,
            filename=unique_filename,
            original_filename=original_filename,
            file_path=relative_path,
            file_type=file_type,
            mime_type=mime_type,
            extension=Path(original_filename).suffix.lstrip(".").lower(),
            size=size,
            uploaded_by_id=uploaded_by_id,
            description=description,
            tags=tags,
            is_public=is_public,
        )
        db.add(file_record)
        db.commit()
        db.refresh(file_record)
        return file_record
    except Exception:
        storage.delete_file_from_disk(settings=settings, file_path=relative_path)
        raise


from pathlib import Path


def get_file(*, db: Session, file_id: UUID, tenant_id) -> Optional[File]:
    """Get file record by ID (tenant-scoped)."""
    return db.query(File).filter(
        File.id == file_id,
        File.tenant_id == tenant_id,
        File.is_active == True
    ).first()


def list_files(*, db: Session, tenant_id, file_type: Optional[str] = None,
               uploaded_by_id: Optional[UUID] = None, skip: int = 0, limit: int = 20,
               search: Optional[str] = None) -> tuple[List[File], int]:
    """List files with pagination (tenant-scoped)."""
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


def update_metadata(*, db: Session, file: File, data: FileUpdateRequest) -> File:
    """Update file metadata."""
    if data.description is not None:
        file.description = data.description
    if data.tags is not None:
        file.tags = data.tags
    if data.is_public is not None:
        file.is_public = data.is_public

    file.modified_at = datetime.utcnow()
    db.add(file)
    db.commit()
    db.refresh(file)
    return file


def soft_delete(*, db: Session, file: File) -> None:
    """Soft delete (la fila queda inactiva, el archivo permanece en disco)."""
    file.is_active = False
    file.modified_at = datetime.utcnow()
    db.add(file)
    db.commit()
