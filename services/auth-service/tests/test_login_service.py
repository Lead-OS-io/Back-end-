"""login service: authenticate + create session row + token pair."""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models.entities import RefreshToken, User
from app.models.enums import UserStatus
from app.services.auth_tokens import hash_refresh
from app.services.login import authenticate_and_open_session
from shared.utils.exceptions import AppError


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _settings(**over) -> Settings:
    base = dict(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 32,
        REDIS_URL="redis://x",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_MINUTES=60,
    )
    base.update(over)
    return Settings(**base)


def _user(s: Session, *, password="correct horse battery staple", status=UserStatus.ACTIVE.value):
    from passlib.context import CryptContext

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    user = User(
        id=uuid.uuid4(),
        email="alice@acme.com",
        password_hash=pwd.hash(password),
        full_name="Alice",
        status=status,
    )
    s.add(user)
    s.commit()
    s.refresh(user)
    return user


def test_login_returns_tokens_and_persists_refresh_row():
    s = _session()
    _user(s)

    outcome = authenticate_and_open_session(
        db=s, settings=_settings(),
        email="alice@acme.com", password="correct horse battery staple",
        ip="127.0.0.1", user_agent="pytest",
    )
    assert outcome.access_token
    assert outcome.refresh_token
    assert outcome.refresh_expires_at > datetime.utcnow()

    rows = s.exec(__import__("sqlmodel").sqlmodel_select(RefreshToken)).all() \
        if False else s.query(RefreshToken).all()
    assert len(rows) == 1
    assert rows[0].ip == "127.0.0.1"
    assert rows[0].user_agent == "pytest"
    assert rows[0].token_hash == hash_refresh(outcome.refresh_token)


def test_login_wrong_password_returns_401():
    s = _session()
    _user(s)
    with pytest.raises(AppError) as exc_info:
        authenticate_and_open_session(
            db=s, settings=_settings(),
            email="alice@acme.com", password="wrong",
        )
    assert exc_info.value.status_code == 401


def test_login_unknown_email_returns_401_same_message():
    s = _session()
    with pytest.raises(AppError) as exc_info:
        authenticate_and_open_session(
            db=s, settings=_settings(),
            email="nobody@x.com", password="whatever",
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid credentials"


def test_login_inactive_user_returns_403():
    s = _session()
    _user(s, status=UserStatus.PENDING_TENANT.value)
    from shared.utils.exceptions import ForbiddenError
    with pytest.raises(ForbiddenError):
        authenticate_and_open_session(
            db=s, settings=_settings(),
            email="alice@acme.com", password="correct horse battery staple",
        )
