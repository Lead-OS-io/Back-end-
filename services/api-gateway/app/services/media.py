import re
from pathlib import Path
from typing import Iterator

from fastapi import Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

CHUNK_SIZE = 64 * 1024
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def file_response_with_range(root: Path, relative: str, request: Request) -> Response:
    base = root.resolve()
    path = (base / relative).resolve()
    if not str(path).startswith(str(base)) or not path.is_file():
        return PlainTextResponse("not found", status_code=404)

    range_header = request.headers.get("range")
    match = _RANGE_RE.fullmatch(range_header.strip()) if range_header else None
    if not match:
        return FileResponse(path)

    size = path.stat().st_size
    start_s, end_s = match.groups()
    if start_s == "" and end_s == "":
        return PlainTextResponse("invalid range", status_code=416)
    if start_s == "":
        start, end = max(0, size - int(end_s)), size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return PlainTextResponse("range not satisfiable", status_code=416)

    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=206,
        media_type="application/octet-stream",
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        },
    )
