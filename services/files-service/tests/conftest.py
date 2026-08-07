import os

os.environ.setdefault("SERVICE_NAME", "files-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler


# Register a SQLite visitor for JSONB so the in-memory sqlite engine can compile
# the MediaResources.meta column (declared as sa_type=JSONB in entities.py).
# The production model remains PostgreSQL JSONB; this shim only affects tests.
def _visit_jsonb(_self, _type, **_kw):
    return "JSON"


SQLiteTypeCompiler.visit_JSONB = _visit_jsonb


class FakeStorage:
    """In-memory StorageBackend used by tests. Compliant with the Protocol."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.policies: dict[str, bool] = {}

    def put_object(self, *, bucket, key, data, size, content_type) -> None:
        assert size == len(data)
        self.objects[(bucket, key)] = bytes(data)

    def get_object(self, *, bucket, key) -> bytes:
        return self.objects[(bucket, key)]

    def delete_object(self, *, bucket, key) -> None:
        self.objects.pop((bucket, key), None)

    def presigned_get_url(self, *, bucket, key, expires_seconds):
        return f"https://test/{bucket}/{key}?exp={expires_seconds}"

    def ensure_bucket(self, *, bucket) -> None:
        self.policies.setdefault(bucket, False)

    def set_bucket_public(self, *, bucket, public) -> None:
        self.policies[bucket] = bool(public)


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch):
    monkeypatch.setattr("app.main.get_storage", lambda _settings: FakeStorage())


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
