"""
Storage service (disco): save_stream, open_range, delete, límite 500MB.
Sin imports de FastAPI; la DB metadata vive en app/services/files.py.
"""
import os
import uuid
from pathlib import Path
from typing import Optional

from shared.utils.exceptions import AppError

CHUNK_SIZE = 8192


def get_file_type(extension: str) -> str:
    """Determine file type based on extension."""
    extension = extension.lower().lstrip(".")

    if extension in ["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"]:
        return "image"
    elif extension in ["pdf", "doc", "docx", "xls", "xlsx", "csv", "txt"]:
        return "document"
    elif extension in ["mp4", "mov", "avi", "mkv", "webm", "flv"]:
        return "video"
    else:
        return "other"


def _safe_join(root: Path, relative: str) -> Path:
    """Resuelve `relative` bajo `root` y rechaza traversal fuera de root."""
    base = root.resolve()
    path = (base / relative).resolve()
    if not str(path).startswith(str(base)):
        raise AppError(400, "invalid storage path")
    return path


def get_absolute_path(*, settings, relative_path: str) -> str:
    return str(_safe_join(Path(settings.STORAGE_PATH), relative_path))


def save_stream(*, settings, file_content: bytes, original_filename: str,
                mime_type: str, tenant_id) -> tuple[str, str, str, str, int]:
    """Guarda el contenido en disco y devuelve
    (absolute_path, relative_path, unique_filename, file_type, size)."""
    if len(file_content) > settings.MAX_FILE_SIZE:
        raise AppError(413, f"File size exceeds maximum allowed ({settings.MAX_FILE_SIZE} bytes)")

    extension = Path(original_filename).suffix.lstrip(".").lower()
    if extension not in settings.ALLOWED_EXTENSIONS:
        raise AppError(400, f"File extension '{extension}' not allowed")

    file_type = get_file_type(extension)
    unique_filename = f"{uuid.uuid4()}.{extension}"

    relative_path = os.path.join(str(tenant_id), file_type, unique_filename)
    absolute_path = os.path.join(settings.STORAGE_PATH, relative_path)

    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    with open(absolute_path, "wb") as f:
        f.write(file_content)

    return absolute_path, relative_path, unique_filename, file_type, len(file_content)


def delete_file_from_disk(*, settings, file_path: str) -> None:
    """Borra el archivo del disco (path traversal-safe)."""
    absolute_path = _safe_join(Path(settings.STORAGE_PATH), file_path)
    if os.path.exists(absolute_path):
        os.remove(absolute_path)


def open_range(*, settings, file_path: str, mime_type: str,
               range_header: Optional[str], extra_headers: Optional[dict] = None):
    """Devuelve una StreamingResponse con soporte HTTP Range (206/416)."""
    from fastapi.responses import FileResponse, StreamingResponse

    absolute_path = _safe_join(Path(settings.STORAGE_PATH), file_path)
    if not os.path.exists(absolute_path):
        raise AppError(404, "File not found on disk")

    file_size = os.path.getsize(absolute_path)
    extra_headers = extra_headers or {}

    if not range_header:
        return FileResponse(absolute_path, media_type=mime_type, headers=extra_headers)

    try:
        range_header = range_header.replace("bytes=", "")
        range_parts = range_header.split("-")
        start = int(range_parts[0]) if range_parts[0] else 0
        end = int(range_parts[1]) if len(range_parts) > 1 and range_parts[1] else file_size - 1
    except (ValueError, IndexError):
        raise AppError(416, "Range Not Satisfiable")

    if start >= file_size or end >= file_size or start > end:
        raise AppError(416, "Range Not Satisfiable")

    chunk_size = end - start + 1

    def iterfile():
        with open(absolute_path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                read_size = min(CHUNK_SIZE, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iterfile(),
        status_code=206,
        media_type=mime_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
            **extra_headers,
        },
    )
