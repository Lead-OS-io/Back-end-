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


@pytest.fixture
def client_public(monkeypatch) -> Iterator[TestClient]:
    """TestClient for the public router (no X-Service-Token, X-User-Id injected).

    Mirrors the structure of `client` in this file: monkey-patches
    `app.main.get_storage` to return a `FakeStorage`, sets up an in-memory
    sqlite engine via SQLModel.metadata.create_all, and yields a TestClient
    whose default headers include `X-User-Id` set to a fresh UUID.
    """
    import uuid as _uuid

    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from app.main import create_app

    fake = FakeStorage()
    monkeypatch.setattr("app.main.get_storage", lambda _settings: fake)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    app = create_app()
    uid = str(_uuid.uuid4())
    with TestClient(app, headers={"X-User-Id": uid}) as c:
        app.state.session_factory = lambda: Session(engine)
        app.state.storage = fake
        app.state.settings = type(
            "S",
            (),
            {
                "INTER_SERVICE_SECRET": "test-inter-service-secret",
                "PRESIGN_TTL_SECONDS": 300,
                "AVATAR_MAX_BYTES": 5 * 1024 * 1024,
                "AVATAR_ALLOWED_MIMETYPES": ("image/jpeg", "image/png", "image/webp"),
            },
        )()
        yield c
