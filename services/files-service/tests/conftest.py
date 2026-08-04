import os
from unittest.mock import MagicMock

os.environ.setdefault("SERVICE_NAME", "files-service")
os.environ.setdefault("PORT", "8004")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://x:x@localhost:5432/x")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import fakeredis
import pytest
from fastapi.testclient import TestClient

from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.service_token import mint_service_token
from shared.db.engine import get_db
from tests import FILE_ID, TENANT_ID, USER_ID

INTER_SERVICE_SECRET = "test-inter-service-secret"


@pytest.fixture
def identity() -> Identity:
    return Identity(user_id=str(USER_ID), tenant_id=str(TENANT_ID), role_id=1, is_superuser=True)


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def svc_headers() -> dict[str, str]:
    return {"X-Service-Token": mint_service_token(secret=INTER_SERVICE_SECRET, issuer="test")}


@pytest.fixture
def client(identity, mock_db, monkeypatch, tmp_path):
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **k: fakeredis.FakeRedis(decode_responses=True))
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        SERVICE_NAME="files-service",
        DATABASE_URL="postgresql+psycopg2://x:x@localhost:5432/x",
        INTER_SERVICE_SECRET="test-inter-service-secret",
        SECRET_KEY="test-secret-key-0123456789abcdef",
        STORAGE_PATH=str(tmp_path),
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_identity] = lambda: identity
    with TestClient(app) as c:
        yield c, tmp_path
