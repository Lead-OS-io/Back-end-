"""
Files controller (FACADE): orquesta app/services/*, traduce a schemas.
Recibe deps como parámetros (no lee Request); el streaming lo delega a storage.
"""
from typing import List, Optional
from uuid import UUID

from sqlmodel import Session

from app.schemas.file import (
    FileInfoResponse, FileListResponse, FileUpdateRequest, FileUploadResponse,
)
from app.serializers.file import file_to_info
from app.services import files as files_service
from app.services import storage as storage_service
from shared.utils.exceptions import AppError


def upload(*, file_content: bytes, original_filename: str, mime_type: str,
           description: Optional[str], tags: Optional[str], is_public: bool,
           db: Session, settings, identity) -> FileUploadResponse:
    file_record = files_service.save_file(
        db=db, settings=settings, file_content=file_content,
        original_filename=original_filename, mime_type=mime_type,
        tenant_id=identity.tenant_id, uploaded_by_id=identity.user_id,
        description=description, tags=tags, is_public=is_public)
    return FileUploadResponse(
        id=file_record.id,
        filename=file_record.original_filename,
        original_filename=file_record.original_filename,
        file_type=file_record.file_type,
        mime_type=file_record.mime_type,
        size=file_record.size,
        url=f"/api/files/{file_record.id}",
    )


def download(*, file_id: UUID, range_header: Optional[str], db: Session,
             settings, identity):
    """Devuelve la respuesta (FileResponse o StreamingResponse con Range)."""
    file_record = files_service.get_file(db=db, file_id=file_id, tenant_id=identity.tenant_id)
    if not file_record:
        raise AppError(404, "File not found")
    return storage_service.open_range(
        settings=settings, file_path=file_record.file_path,
        mime_type=file_record.mime_type, range_header=range_header,
        extra_headers={"Content-Disposition": f'attachment; filename="{file_record.original_filename}"'})


def info(*, file_id: UUID, db: Session, settings, identity) -> FileInfoResponse:
    file_record = files_service.get_file(db=db, file_id=file_id, tenant_id=identity.tenant_id)
    if not file_record:
        raise AppError(404, "File not found")
    return file_to_info(file_record)


def list_files(*, page: int, size: int, file_type: Optional[str],
               uploaded_by_id: Optional[UUID], search: Optional[str],
               db: Session, settings, identity) -> FileListResponse:
    files, total = files_service.list_files(
        db=db, tenant_id=identity.tenant_id, file_type=file_type,
        uploaded_by_id=uploaded_by_id, skip=(page - 1) * size, limit=size, search=search)
    return FileListResponse(
        items=[file_to_info(f) for f in files], total=total, page=page, size=size,
        pages=(total + size - 1) // size if total > 0 else 0)


def update(*, file_id: UUID, data: FileUpdateRequest, db: Session, settings,
           identity) -> FileInfoResponse:
    file_record = files_service.get_file(db=db, file_id=file_id, tenant_id=identity.tenant_id)
    if not file_record:
        raise AppError(404, "File not found")
    updated = files_service.update_metadata(db=db, file=file_record, data=data)
    return file_to_info(updated)


def delete(*, file_id: UUID, permanent: bool, db: Session, settings,
           identity) -> None:
    file_record = files_service.get_file(db=db, file_id=file_id, tenant_id=identity.tenant_id)
    if not file_record:
        raise AppError(404, "File not found")
    files_service.soft_delete(db=db, file=file_record)
    if permanent:
        storage_service.delete_file_from_disk(settings=settings,
                                               file_path=file_record.file_path)
