"""Tests for MediaManager using FakeStorage and an in-memory sqlite."""
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.entities import MediaResources
from app.models.enums import MediaPurpose
from app.storage.manager import MediaManager

from tests.conftest import FakeStorage


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


@pytest.fixture
def manager() -> MediaManager:
    return MediaManager(db=_session(), backend=FakeStorage())


def test_upload_avatar_creates_media_resources_row(manager):
    user_id = uuid.uuid4()
    media = manager.upload_avatar(
        tenant_id=None,
        user_id=user_id,
        content=b"PNG_DATA",
        filename="avatar.png",
        content_type="image/png",
        size_bytes=len(b"PNG_DATA"),
    )

    assert media.id is not None
    assert media.user_id == user_id
    assert media.purpose == MediaPurpose.PROFILE_PHOTO
    assert media.mimetype == "image/png"
    assert media.bucket == "avatars"
    assert media.size_bytes == len(b"PNG_DATA")


def test_upload_avatar_replaces_existing(manager):
    user_id = uuid.uuid4()
    first = manager.upload_avatar(
        tenant_id=None, user_id=user_id, content=b"OLD",
        filename="a.png", content_type="image/png", size_bytes=3,
    )
    second = manager.upload_avatar(
        tenant_id=None, user_id=user_id, content=b"NEW_DATA",
        filename="b.png", content_type="image/png", size_bytes=8,
    )

    assert first.id != second.id
    assert first.path != second.path
    assert second.size_bytes == 8
    assert manager.get_avatar(user_id=user_id).id == second.id


def test_get_avatar_returns_none_if_not_set(manager):
    assert manager.get_avatar(user_id=uuid.uuid4()) is None


def test_delete_avatar_removes_object_and_row(manager):
    user_id = uuid.uuid4()
    storage = manager._backend
    manager.upload_avatar(
        tenant_id=None, user_id=user_id, content=b"PNG",
        filename="a.png", content_type="image/png", size_bytes=3,
    )
    assert manager.delete_avatar(user_id=user_id) is True
    assert manager.get_avatar(user_id=user_id) is None
    remaining = [
        v for (b, k), v in storage.objects.items() if b == "avatars"
    ]
    assert remaining == []


def test_delete_avatar_returns_false_when_no_avatar(manager):
    assert manager.delete_avatar(user_id=uuid.uuid4()) is False
