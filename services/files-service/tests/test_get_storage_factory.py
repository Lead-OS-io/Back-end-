"""Behaviour of the storage backend factory."""
import pytest

from app.config import Settings
from app.storage import get_storage
from app.storage.local_backend import LocalBackend
from app.storage.minio_backend import MinioBackend


def _s(**over) -> Settings:
    base = dict(
        SERVICE_NAME="files-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 40,
        REDIS_URL="redis://x",
    )
    base.update(over)
    return Settings(**base)


def test_factory_returns_minio_backend_by_default():
    s = _s()
    assert isinstance(get_storage(s), MinioBackend)


def test_factory_returns_local_when_requested():
    s = _s(STORAGE_BACKEND="local")
    assert isinstance(get_storage(s), LocalBackend)


def test_factory_raises_for_unknown_backend():
    s = _s(STORAGE_BACKEND="s3")
    with pytest.raises(ValueError, match="unknown STORAGE_BACKEND"):
        get_storage(s)
