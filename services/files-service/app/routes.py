"""
API routes for files service with streaming support
"""
import os
from typing import Optional, Generator
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Header, Query, UploadFile, File as FastAPIFile, Request
from app.redis_cache import cached
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session
from sqlalchemy import text
import jwt
import math

from app.database import engine
from app.config import settings
from app.services import FileService
from app.schemas import (
    FileUploadResponse, FileInfoResponse, FileListResponse, FileUpdateRequest
)

router = APIRouter()


async def _read_upload_bounded(file: UploadFile, max_size: int) -> bytes:
    """Read the upload in chunks, aborting as soon as the running total
    exceeds max_size - avoids buffering an arbitrarily large body in memory
    before the size check (the old code read() the whole file first)."""
    chunks = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File size exceeds maximum allowed ({max_size} bytes)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def verify_token(authorization: str = Header(...)):
    """Verify JWT signature and return the payload"""
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")


def get_tenant_id(
    x_tenant_id: str = Header(...),
    token: dict = Depends(verify_token),
) -> UUID:
    """Resolve tenant from X-Tenant-ID and enforce it matches the JWT tenant_id claim."""
    try:
        header_tenant = UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID header")

    token_tenant = token.get("tenant_id")
    if not token_tenant:
        raise HTTPException(status_code=401, detail="Token missing tenant_id")
    if str(header_tenant) != str(token_tenant):
        raise HTTPException(status_code=403, detail="X-Tenant-ID does not match token tenant_id")
    return header_tenant


def get_tenant_db(tenant_id: UUID = Depends(get_tenant_id)) -> Generator[Session, None, None]:
    """Same session as get_db, but scoped to the validated tenant for RLS:
    sets the app.tenant_id GUC read by the policies in db/rls_policies.sql.
    Harmless no-op until that SQL is applied (see db/README.md)."""
    with Session(engine) as session:
        session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        yield session


def range_requests_response(
    file_path: str,
    content_type: str,
    range_header: Optional[str] = None,
    download_filename: Optional[str] = None,
    is_video: bool = False,
):
    """
    Handle Range requests for video streaming
    """
    file_size = os.path.getsize(file_path)

    # A Range header can be sent for any file, not just videos. Only videos
    # are meant to render inline (e.g. an HTML5 <video> tag) - anything else
    # gets forced to download, since the mime_type is client-supplied at
    # upload time and rendering it inline (e.g. a .txt uploaded as
    # text/html) would be a stored-XSS vector on this origin.
    extra_headers = {}
    if not is_video:
        content_disposition = "attachment"
        if download_filename:
            content_disposition += f'; filename="{download_filename}"'
        extra_headers["Content-Disposition"] = content_disposition

    # If no range header, send full file
    if not range_header:
        def iterfile():
            with open(file_path, "rb") as f:
                yield from f

        return StreamingResponse(
            iterfile(),
            media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                **extra_headers,
            }
        )
    
    # Parse range header
    try:
        range_header = range_header.replace("bytes=", "")
        range_parts = range_header.split("-")
        start = int(range_parts[0]) if range_parts[0] else 0
        end = int(range_parts[1]) if len(range_parts) > 1 and range_parts[1] else file_size - 1
    except (ValueError, IndexError):
        raise HTTPException(status_code=416, detail="Range Not Satisfiable")
    
    # Validate range
    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable")
    
    chunk_size = end - start + 1
    
    def iterfile():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                read_size = min(8192, remaining)  # Read in 8KB chunks
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data
    
    return StreamingResponse(
        iterfile(),
        status_code=206,  # Partial Content
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            **extra_headers,
        }
    )


# =============================================================================
# FILE UPLOAD
# =============================================================================

@router.post("/api/files", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    request: Request,
    file: UploadFile = FastAPIFile(...),
    description: Optional[str] = None,
    tags: Optional[str] = None,
    is_public: bool = False,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Upload a file"""
    # Extract user_id from token
    user_id = UUID(token.get("user_id"))

    # Reject oversized uploads by declared Content-Length before reading anything.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File size exceeds maximum allowed ({settings.MAX_FILE_SIZE} bytes)",
                )
        except ValueError:
            pass

    content = await _read_upload_bounded(file, settings.MAX_FILE_SIZE)
    
    try:
        file_record = await FileService.save_file(
            db,
            content,
            file.filename,
            file.content_type,
            tenant_id,
            user_id,
            description,
            tags,
            is_public
        )
        
        return FileUploadResponse(
            id=file_record.id,
            filename=file_record.filename,
            original_filename=file_record.original_filename,
            file_type=file_record.file_type,
            mime_type=file_record.mime_type,
            size=file_record.size,
            url=f"/api/files/{file_record.id}"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# FILE DOWNLOAD (WITH STREAMING FOR VIDEOS)
# =============================================================================

@router.get("/api/files/{file_id}")
def download_file(
    file_id: UUID,
    range: Optional[str] = Header(None),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Download a file (supports Range requests for streaming)"""
    file_record = FileService.get_file(db, file_id, tenant_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    absolute_path = FileService.get_absolute_path(file_record)
    
    if not os.path.exists(absolute_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    
    # For videos, use range requests
    if file_record.file_type == 'video' or range:
        return range_requests_response(
            absolute_path,
            file_record.mime_type,
            range,
            download_filename=file_record.original_filename,
            is_video=(file_record.file_type == 'video'),
        )
    
    # For other files, send directly
    return FileResponse(
        absolute_path,
        media_type=file_record.mime_type,
        filename=file_record.original_filename
    )


# =============================================================================
# FILE INFO
# =============================================================================

@router.get("/api/files/{file_id}/info", response_model=FileInfoResponse)
@cached(ttl=600, prefix="file_info")
def get_file_info(
    request: Request,
    file_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Get file information"""
    file_record = FileService.get_file(db, file_id, tenant_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    return file_record


# =============================================================================
# FILE LIST
# =============================================================================

@router.get("/api/files", response_model=FileListResponse)
@cached(ttl=300, prefix="file_list")
def list_files(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    file_type: Optional[str] = Query(None),
    uploaded_by_id: Optional[UUID] = Query(None),
    search: Optional[str] = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """List files with pagination"""
    skip = (page - 1) * size
    files, total = FileService.list_files(
        db, tenant_id, file_type, uploaded_by_id, skip, size, search
    )
    
    return FileListResponse(
        items=files,
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total > 0 else 0
    )


# =============================================================================
# FILE UPDATE
# =============================================================================

@router.put("/api/files/{file_id}", response_model=FileInfoResponse)
def update_file(
    file_id: UUID,
    file_data: FileUpdateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Update file metadata"""
    file_record = FileService.get_file(db, file_id, tenant_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    updated_file = FileService.update_file(
        db, file_record,
        file_data.description,
        file_data.tags,
        file_data.is_public
    )
    return updated_file


# =============================================================================
# FILE DELETE
# =============================================================================

@router.delete("/api/files/{file_id}", status_code=204)
def delete_file(
    file_id: UUID,
    permanent: bool = Query(False),
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Delete file (soft delete by default, permanent if specified)"""
    file_record = FileService.get_file(db, file_id, tenant_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Soft delete
    FileService.delete_file(db, file_record)
    
    # Permanent delete if requested
    if permanent:
        FileService.delete_file_from_disk(file_record)
    
    return None



