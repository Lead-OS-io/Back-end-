import uuid
from datetime import datetime, timedelta

import pytest
from passlib.context import CryptContext
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.models.entities import RefreshToken, User
from app.models.enums import UserStatus
from app.services.auth_tokens import hash_refresh, mint_refresh_token
from app.services.refresh import rotate_refresh
from shared.utils.exceptions import AppError


_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _settings() -> Settings:
    return Settings(
        SERVICE_NAME="auth-service",
        DATABASE_URL="sqlite:///:memory:",
        INTER_SERVICE_SECRET="x",
        SECRET_KEY="x" * 32,
        REDIS_URL="redis://x",
        ACCESS_TOKEN_EXPIRE_MINUTES=15,
        REFRESH_TOKEN_EXPIRE_MINUTES=60,
    )


def _seed(db: Session):
    user = User(
        id=uuid.uuid4(),
        email="a@a.com",
        password_hash=_PWD.hash("x"),
        status=UserStatus.ACTIVE.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    raw = mint_refresh_token()
    row = RefreshToken(
        user_id=user.id, tenant_id=None,
        token_hash=hash_refresh(raw),
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return user, raw


def test_refresh_rotates_and_revokes_old():
    s = _session()
    user, raw = _seed(s)

    outcome = rotate_refresh(db=s, settings=_settings(), raw_refresh_token=raw)

    assert outcome.user.id == user.id
    assert outcome.new_refresh_token != raw

    new_rows = (
        s.query(RefreshToken)
        .filter(RefreshToken.revoked_at.is_(None))
        .all()
    )
    assert len(new_rows) == 1
    assert new_rows[0].id == outcome.new_refresh_row.id


def test_refresh_reuses_revoked_token_revokes_all_user_tokens():
    s = _session()
    user, raw = _seed(s)
    rotate_refresh(db=s, settings=_settings(), raw_refresh_token=raw)

    with pytest.raises(AppError) as exc:
        rotate_refresh(
            db=s, settings=_settings(),
            raw_refresh_token=raw,
        )
    assert exc.value.status_code == 401
    rows = s.query(RefreshToken).filter_by(user_id=user.id).all()
    assert all(r.revoked_at is not None for r in rows)


def test_refresh_unknown_token_raises_401():
    s = _session()
    _seed(s)
    with pytest.raises(AppError):
        rotate_refresh(
            db=s, settings=_settings(),
            raw_refresh_token="never-issued-token",
        )


def test_refresh_expired_token_revokes_and_rejects():
    s = _session()
    user, raw = _seed(s)

    s.query(RefreshToken).update({"expires_at": datetime.utcnow()})
    s.commit()

    with pytest.raises(AppError):
        rotate_refresh(
            db=s, settings=_settings(),
            raw_refresh_token=raw,
        )
    rows = s.query(RefreshToken).filter_by(user_id=user.id).all()
    assert all(r.revoked_at is not None for r in rows)
