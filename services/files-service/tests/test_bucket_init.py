"""Bucket initialization runs in lifespan for each INIT_BUCKETS entry."""
from fastapi.testclient import TestClient


def test_lifespan_initialises_buckets(monkeypatch):
    from app.config import Settings
    from app.storage import get_storage
    from tests.conftest import FakeStorage

    fake = FakeStorage()

    def fake_get_storage(settings: Settings):
        return fake

    monkeypatch.setattr("app.main.get_storage", fake_get_storage)

    settings = Settings(
        SERVICE_NAME="files-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 40,
        REDIS_URL="redis://x",
        INIT_BUCKETS=(("avatars", False), ("media", False), ("public_assets", True)),
    )

    from app.main import create_app

    app = create_app(settings)
    with TestClient(app):
        pass

    assert fake.policies == {
        "avatars": False,
        "media": False,
        "public_assets": True,
    }


def test_bucket_init_is_idempotent(monkeypatch):
    """ensure_bucket + set_bucket_public can be called twice without error."""
    from app.config import Settings
    from tests.conftest import FakeStorage

    fake = FakeStorage()

    def fake_get_storage(settings: Settings):
        return fake

    monkeypatch.setattr("app.main.get_storage", fake_get_storage)
    settings = Settings(
        SERVICE_NAME="files-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 40,
        REDIS_URL="redis://x",
        INIT_BUCKETS=(("avatars", False),),
    )

    from app.main import create_app

    app = create_app(settings)
    with TestClient(app):
        with TestClient(app):
            pass

    assert fake.policies == {"avatars": False}
