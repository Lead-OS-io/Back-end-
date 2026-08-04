"""Tests de lógica de services: storage real sobre tmp_path + serializers."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services import storage
from app.services import files as files_service


class _Settings:
    STORAGE_PATH = ""
    MAX_FILE_SIZE = 500 * 1024 * 1024
    ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp",
                          "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt",
                          "mp4", "mov", "avi", "mkv", "webm"]


@pytest.fixture
def settings(tmp_path: Path):
    s = _Settings()
    s.STORAGE_PATH = str(tmp_path)
    return s


def test_save_and_open_roundtrip(settings):
    abs_path, rel_path, filename, file_type, size = storage.save_stream(
        settings=settings, file_content=b"hello world", original_filename="a.txt",
        mime_type="text/plain", tenant_id="t1")
    assert file_type == "document"
    assert size == 11
    assert Path(abs_path).exists()
    assert Path(rel_path).parent.parent.name == "t1"


def test_save_rejects_oversize(settings):
    settings.MAX_FILE_SIZE = 5
    with pytest.raises(Exception):
        storage.save_stream(settings=settings, file_content=b"x" * 10,
                            original_filename="a.txt", mime_type="text/plain",
                            tenant_id="t1")


def test_save_rejects_disallowed_extension(settings):
    with pytest.raises(Exception):
        storage.save_stream(settings=settings, file_content=b"x", original_filename="a.exe",
                            mime_type="application/x-msdownload", tenant_id="t1")


def test_delete_from_disk(settings):
    _, rel_path, *_ = storage.save_stream(settings=settings, file_content=b"x",
                                          original_filename="a.txt", mime_type="text/plain",
                                          tenant_id="t1")
    storage.delete_file_from_disk(settings=settings, file_path=rel_path)
    assert not Path(settings.STORAGE_PATH, rel_path).exists()


def test_traversal_is_rejected(settings):
    with pytest.raises(Exception):
        storage.open_range(settings=settings, file_path="../../etc/passwd",
                           mime_type="text/plain", range_header=None)


def test_open_range_206(settings):
    _, rel_path, *_ = storage.save_stream(settings=settings, file_content=b"0123456789",
                                          original_filename="a.txt", mime_type="text/plain",
                                          tenant_id="t1")
    resp = storage.open_range(settings=settings, file_path=rel_path,
                              mime_type="text/plain", range_header="bytes=2-5")
    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 2-5/10"


def test_open_range_invalid_is_416(settings):
    _, rel_path, *_ = storage.save_stream(settings=settings, file_content=b"0123456789",
                                          original_filename="a.txt", mime_type="text/plain",
                                          tenant_id="t1")
    with pytest.raises(Exception):
        storage.open_range(settings=settings, file_path=rel_path,
                           mime_type="text/plain", range_header="bytes=50-60")


def test_save_file_metadata_roundtrip(settings):
    db = MagicMock()
    record = files_service.save_file(
        db=db, settings=settings, file_content=b"hi", original_filename="a.txt",
        mime_type="text/plain", tenant_id="t1", uploaded_by_id="u1",
        description="d", tags="a,b", is_public=True)
    assert record.original_filename == "a.txt"
    assert record.is_public is True
