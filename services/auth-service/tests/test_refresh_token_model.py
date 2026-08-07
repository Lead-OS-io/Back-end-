"""Schema-level tests for the RefreshToken model."""
import uuid

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.entities import RefreshToken, User
from app.models.enums import UserStatus


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_refresh_token_can_be_persisted_with_hash():
    s = _session()
    user = User(
        email="x@x.com",
        password_hash="$2b$12$xxxx",
        full_name="X",
        status=UserStatus.ACTIVE.value,
    )
    s.add(user)
    s.commit()
    s.refresh(user)

    rt = RefreshToken(
        user_id=user.id,
        tenant_id=None,
        token_hash="deadbeef" * 8,
        expires_at=__import__("datetime").datetime.utcnow(),
    )
    s.add(rt)
    s.commit()
    s.refresh(rt)

    fetched = s.get(RefreshToken, rt.id)
    assert fetched.token_hash == "deadbeef" * 8

