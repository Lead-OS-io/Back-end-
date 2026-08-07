"""Refresh-token rotation. Reuse of a revoked refresh revokes ALL of a user's
sessions as a precaution against stolen tokens."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import update
from sqlmodel import Session, select

from app.config import Settings
from app.models.entities import RefreshToken, User
from app.models.enums import UserStatus
from app.services.auth_tokens import (
    hash_refresh,
    mint_access_token,
    mint_refresh_token,
)
from shared.utils.exceptions import AppError


@dataclass(frozen=True)
class RefreshOutcome:
    user: User
    access_token: str
    expires_at: int
    new_refresh_token: str
    refresh_expires_at: datetime
    new_refresh_row: RefreshToken


def _revoke_all_for_user(db: Session, user_id) -> int:
    statement = (
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.utcnow(), revoked_reason="reuse_detected")
    )
    result = db.exec(statement)
    db.commit()
    return result.rowcount or 0


def rotate_refresh(
    *,
    db: Session,
    settings: Settings,
    raw_refresh_token: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> RefreshOutcome:
    digest = hash_refresh(raw_refresh_token)
    statement = select(RefreshToken).where(RefreshToken.token_hash == digest)
    row: Optional[RefreshToken] = db.exec(statement).first()

    if row is None or row.revoked_at is not None or row.expires_at <= datetime.utcnow():
        if row is not None:
            _revoke_all_for_user(db, row.user_id)
        raise AppError(401, "invalid refresh token")

    user: Optional[User] = db.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise AppError(401, "invalid refresh token")

    access_token, expires_at = mint_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        status=user.status,
        ttl_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        secret=settings.SECRET_KEY,
    )

    new_raw = mint_refresh_token()
    new_expires_at = datetime.utcnow() + timedelta(
        minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES
    )
    new_row = RefreshToken(
        user_id=user.id,
        tenant_id=user.tenant_id,
        token_hash=hash_refresh(new_raw),
        expires_at=new_expires_at,
        ip=ip,
        user_agent=user_agent,
    )
    db.add(new_row)
    row.revoked_at = datetime.utcnow()
    row.revoked_reason = "rotated"
    db.commit()
    db.refresh(new_row)

    return RefreshOutcome(
        user=user,
        access_token=access_token,
        expires_at=expires_at,
        new_refresh_token=new_raw,
        refresh_expires_at=new_expires_at,
        new_refresh_row=new_row,
    )


__all__ = ["RefreshOutcome", "rotate_refresh"]
