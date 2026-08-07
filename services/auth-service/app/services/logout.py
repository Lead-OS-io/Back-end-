"""Logout: revoke the refresh token row."""
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models.entities import RefreshToken
from app.services.auth_tokens import hash_refresh


def revoke_session_for_token(
    *, db: Session, raw_refresh_token: Optional[str]
) -> bool:
    if not raw_refresh_token:
        return False
    digest = hash_refresh(raw_refresh_token)
    row = db.exec(
        select(RefreshToken).where(RefreshToken.token_hash == digest)
    ).first()
    if row is None:
        return False
    row.revoked_at = datetime.utcnow()
    row.revoked_reason = "user_logout"
    db.commit()
    db.refresh(row)
    return True


__all__ = ["revoke_session_for_token"]
