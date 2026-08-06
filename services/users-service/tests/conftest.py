import os

os.environ.setdefault("SERVICE_NAME", "users-service")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("INTER_SERVICE_SECRET", "test-inter-service-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
