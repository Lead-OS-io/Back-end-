"""Contrato del router de files-service (Task 30)."""
import uuid
from datetime import datetime

from tests import FILE_ID, TENANT_ID, USER_ID


class _StubFile:
    def __init__(self, **kw):
        self.id = FILE_ID
        self.tenant_id = TENANT_ID
        self.filename = "1.txt"
        self.original_filename = "hello.txt"
        self.file_path = "t/1.txt"  # relativo a STORAGE_PATH
        self.file_type = "document"
        self.mime_type = "text/plain"
        self.extension = "txt"
        self.size = 11
        self.uploaded_by_id = USER_ID
        self.description = None
        self.tags = None
        self.is_public = False
        self.is_active = True
        self.created_at = datetime.utcnow()
        self.modified_at = datetime.utcnow()
        for k, v in kw.items():
            setattr(self, k, v)


def _prepare_disk(client_fixture) -> _StubFile:
    """Crea el archivo real en STORAGE_PATH y devuelve el stub de metadata."""
    client, tmp_path = client_fixture
    storage = tmp_path / "t"
    storage.mkdir(exist_ok=True)
    (storage / "1.txt").write_bytes(b"01234567890")
    return _StubFile()


def test_health_ok(client):
    c, _ = client
    assert c.get("/health").status_code == 200


def test_upload_returns_201_with_metadata(client, svc_headers, monkeypatch):
    c, _ = client
    monkeypatch.setattr("app.services.files.save_file", lambda **kwargs: _StubFile())
    resp = c.post("/api/files", files={"file": ("hello.txt", b"0123456789", "text/plain")},
                  data={"description": "d", "tags": "a,b"},
                  headers=svc_headers)
    assert resp.status_code == 201
    assert resp.json()["id"] == str(FILE_ID)
    assert resp.json()["filename"] == "hello.txt"


def test_upload_oversize_is_413(client, svc_headers):
    c, _ = client
    big = b"x" * (500 * 1024 * 1024 + 1)
    resp = c.post("/api/files", files={"file": ("big.bin", big, "application/octet-stream")},
                  headers=svc_headers)
    assert resp.status_code == 413


def test_download_returns_bytes(client, svc_headers, monkeypatch):
    stub = _prepare_disk(client)
    monkeypatch.setattr("app.services.files.get_file", lambda **kwargs: stub)
    c, _ = client
    resp = c.get(f"/api/files/{FILE_ID}", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.content == b"01234567890"


def test_download_with_range_returns_206(client, svc_headers, monkeypatch):
    stub = _prepare_disk(client)
    monkeypatch.setattr("app.services.files.get_file", lambda **kwargs: stub)
    c, _ = client
    resp = c.get(f"/api/files/{FILE_ID}", headers={**svc_headers, "Range": "bytes=2-5"})
    assert resp.status_code == 206
    assert resp.content == b"2345"
    assert resp.headers["Content-Range"] == "bytes 2-5/11"


def test_download_missing_file_is_404(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.files.get_file", lambda **kwargs: None)
    c, _ = client
    assert c.get(f"/api/files/{FILE_ID}", headers=svc_headers).status_code == 404


def test_file_info(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.files.get_file", lambda **kwargs: _StubFile())
    c, _ = client
    resp = c.get(f"/api/files/{FILE_ID}/info", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(FILE_ID)


def test_list_files_tenant_scoped(client, svc_headers, monkeypatch):
    c, _ = client
    captured = {}

    def fake_list_files(**kwargs):
        captured.update(kwargs)
        return ([_StubFile()], 1)

    monkeypatch.setattr("app.services.files.list_files", fake_list_files)
    resp = c.get("/api/files", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    # El tenant de la identity se filtra SIEMPRE (aislamiento, RLS eliminado).
    assert str(captured["tenant_id"]) == str(TENANT_ID)


def test_update_file(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.files.get_file", lambda **kwargs: _StubFile())
    monkeypatch.setattr("app.services.files.update_metadata",
                        lambda **kwargs: _StubFile(description="new"))
    c, _ = client
    resp = c.put(f"/api/files/{FILE_ID}", json={"description": "new"}, headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["description"] == "new"


def test_delete_file(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.files.get_file", lambda **kwargs: _StubFile())
    monkeypatch.setattr("app.services.files.soft_delete", lambda **kwargs: None)
    c, _ = client
    assert c.delete(f"/api/files/{FILE_ID}", headers=svc_headers).status_code == 204


def test_missing_service_token_is_401(client):
    c, _ = client
    assert c.get("/api/files").status_code == 401
