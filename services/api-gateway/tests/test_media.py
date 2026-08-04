from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.services.media import file_response_with_range


@pytest.fixture
def media_root(tmp_path: Path) -> Path:
    root = tmp_path / "media"
    root.mkdir()
    (root / "hello.txt").write_bytes(b"0123456789")
    return root


@pytest.fixture
def client(media_root: Path) -> TestClient:
    app = FastAPI()

    @app.get("/media/{p:path}")
    def media(p: str, request: Request):
        return file_response_with_range(media_root, p, request)

    return TestClient(app)


def test_full_file_without_range(client):
    resp = client.get("/media/hello.txt")
    assert resp.status_code == 200 and resp.content == b"0123456789"


def test_range_request_returns_206(client):
    resp = client.get("/media/hello.txt", headers={"Range": "bytes=2-5"})
    assert resp.status_code == 206
    assert resp.content == b"2345"
    assert resp.headers["Content-Range"] == "bytes 2-5/10"


def test_suffix_range(client):
    resp = client.get("/media/hello.txt", headers={"Range": "bytes=-3"})
    assert resp.status_code == 206 and resp.content == b"789"


def test_invalid_range_is_416(client):
    assert client.get("/media/hello.txt", headers={"Range": "bytes=50-60"}).status_code == 416


def test_path_traversal_is_404(client):
    assert client.get("/media/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_missing_file_is_404(client):
    assert client.get("/media/nope.txt").status_code == 404
