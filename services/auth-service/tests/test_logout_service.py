"""logout service: revoke the refresh row by sha256(raw)."""
import uuid
from datetime import datetime

import pytest
from passlib.context import CryptContext
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.entities import RefreshToken, User
from app.services.auth_tokens import hash_refresh, mint_refresh_token
from app.services.logout import revoke_session_for_token


_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session):
    user = User(
        id=uuid.uuid4(), email="x@x.com",
        password_hash=_PWD.hash("x"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    raw = mint_refresh_token()
    row = RefreshToken(
        user_id=user.id, tenant_id=None,
        token_hash=hash_refresh(raw), expires_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return user, row, raw


def test_logout_revokes_target_refresh():
    s = _session()
    _, row, raw = _seed(s)
    assert revoke_session_for_token(db=s, raw_refresh_token=raw) is True
    s.refresh(row)
    assert row.revoked_at is not None
    assert row.revoked_reason == "user_logout"


def test_logout_unknown_token_returns_false():
    s = _session()
    assert revoke_session_for_token(db=s, raw_refresh_token="never-issued") is False


def test_logout_with_none_token_is_noop():
    s = _session()
    assert revoke_session_for_token(db=s, raw_refresh_token=None) is False
