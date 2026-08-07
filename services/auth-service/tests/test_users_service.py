import uuid

import pytest
from passlib.context import CryptContext
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.entities import User
from app.models.enums import UserStatus
from app.services.users import get_user_by_id, update_user
from shared.utils.exceptions import NotFoundError


_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email="x@x.com",
        password_hash=_PWD.hash("x"),
        full_name="Original",
        phone="+14155550100",
        status=UserStatus.ACTIVE.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_get_user_by_id_returns_user():
    s = _session()
    user = _seed(s)
    assert get_user_by_id(db=s, user_id=user.id).id == user.id


def test_get_user_by_id_raises_not_found_for_unknown_id():
    s = _session()
    with pytest.raises(NotFoundError):
        get_user_by_id(db=s, user_id=uuid.uuid4())


def test_update_user_changes_full_name():
    s = _session()
    user = _seed(s)
    updated = update_user(
        db=s, user_id=user.id, full_name="New Name", phone=None,
    )
    assert updated.full_name == "New Name"


def test_update_user_changes_phone_only():
    s = _session()
    user = _seed(s)
    updated = update_user(
        db=s, user_id=user.id, full_name=None, phone="+34999999000",
    )
    assert updated.full_name == "Original"
    assert updated.phone == "+34999999000"


def test_update_user_does_not_touch_email():
    s = _session()
    user = _seed(s)
    updated = update_user(
        db=s, user_id=user.id, full_name="X", phone=None,
    )
    assert updated.email == user.email
