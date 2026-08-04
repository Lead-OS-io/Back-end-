from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File as FastAPIFile, Header, Query, Request, UploadFile
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.schemas.file import (
    FileInfoResponse, FileListResponse, FileUpdateRequest, FileUploadResponse,
)
from shared.auth.dependencies import Identity, get_current_identity
from shared.db.engine import get_db
from shared.utils.exceptions import AppError

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/api/files", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    request: Request,
    file: UploadFile = FastAPIFile(...),
    description: Optional[str] = None,
    tags: Optional[str] = None,
    is_public: bool = False,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: Identity = Depends(get_current_identity),
) -> FileUploadResponse:
    settings = request.app.state.settings
    # Rechaza uploads oversized por Content-Length antes de leer nada.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.MAX_FILE_SIZE:
                raise AppError(413, f"File size exceeds maximum allowed ({settings.MAX_FILE_SIZE} bytes)")
        except ValueError:
            pass

    content = await _read_upload_bounded(file, settings.MAX_FILE_SIZE)
    return controller.upload(
        file_content=content, original_filename=file.filename or "file",
        mime_type=file.content_type or "application/octet-stream",
        description=description, tags=tags, is_public=is_public,
        db=db, settings=settings, identity=identity)


@router.get("/api/files/{file_id}")
def download_file(
    file_id: UUID,
    range: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: Identity = Depends(get_current_identity),
):
    return controller.download(file_id=file_id, range_header=range, db=db,
                               settings=settings, identity=identity)


@router.get("/api/files/{file_id}/info", response_model=FileInfoResponse)
def get_file_info(
    file_id: UUID,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: Identity = Depends(get_current_identity),
) -> FileInfoResponse:
    return controller.info(file_id=file_id, db=db, settings=settings, identity=identity)


@router.get("/api/files", response_model=FileListResponse)
def list_files(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    file_type: Optional[str] = Query(None),
    uploaded_by_id: Optional[UUID] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: Identity = Depends(get_current_identity),
) -> FileListResponse:
    return controller.list_files(page=page, size=size, file_type=file_type,
                                 uploaded_by_id=uploaded_by_id, search=search,
                                 db=db, settings=settings, identity=identity)


@router.put("/api/files/{file_id}", response_model=FileInfoResponse)
def update_file(
    file_id: UUID,
    file_data: FileUpdateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: Identity = Depends(get_current_identity),
) -> FileInfoResponse:
    return controller.update(file_id=file_id, data=file_data, db=db,
                             settings=settings, identity=identity)


@router.delete("/api/files/{file_id}", status_code=204)
def delete_file(
    file_id: UUID,
    permanent: bool = Query(False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    identity: Identity = Depends(get_current_identity),
) -> None:
    return controller.delete(file_id=file_id, permanent=permanent, db=db,
                             settings=settings, identity=identity)


async def _read_upload_bounded(file: UploadFile, max_size: int) -> bytes:
    """Lee el upload en chunks, abortando si supera max_size."""
    content = bytearray()
    while True:
        chunk = await file.read(8192)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > max_size:
            raise AppError(413, f"File size exceeds maximum allowed ({max_size} bytes)")
    return bytes(content)
