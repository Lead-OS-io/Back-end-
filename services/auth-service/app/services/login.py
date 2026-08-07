"""Login flow: authenticate credentials and open a refresh-token session."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from passlib.context import CryptContext
from sqlmodel import Session, select

from app.config import Settings
from app.models.entities import RefreshToken, User
from app.models.enums import UserStatus
from app.services.auth_tokens import (
    hash_refresh,
    mint_access_token,
    mint_refresh_token,
)
from shared.utils.exceptions import AppError, ForbiddenError

_PWD = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass(frozen=True)
class LoginOutcome:
    user: User
    access_token: str
    expires_at: int
    refresh_token: str
    refresh_expires_at: datetime
    refresh_row: RefreshToken


def _verify_password(plain: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return _PWD.verify(plain, hashed)
    except ValueError:
        return False


def authenticate_and_open_session(
    *,
    db: Session,
    settings: Settings,
    email: str,
    password: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> LoginOutcome:
    statement = select(User).where(User.email == email)
    user = db.exec(statement).first()
    if user is None or not _verify_password(password, user.password_hash):
        raise AppError(401, "invalid credentials")
    if user.status != UserStatus.ACTIVE.value:
        raise ForbiddenError("user not active")

    access_token, expires_at = mint_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=user.status,
        ttl_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        secret=settings.SECRET_KEY,
    )

    refresh_raw = mint_refresh_token()
    refresh_expires_at = datetime.utcnow() + timedelta(
        minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES
    )
    row = RefreshToken(
        user_id=user.id,
        tenant_id=user.tenant_id,
        token_hash=hash_refresh(refresh_raw),
        expires_at=refresh_expires_at,
        ip=ip,
        user_agent=user_agent,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return LoginOutcome(
        user=user,
        access_token=access_token,
        expires_at=expires_at,
        refresh_token=refresh_raw,
        refresh_expires_at=refresh_expires_at,
        refresh_row=row,
    )


__all__ = ["LoginOutcome", "authenticate_and_open_session"]
