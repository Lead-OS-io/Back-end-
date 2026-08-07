"""User CRUD: get-by-id and update /me (only full_name and phone)."""
import uuid
from typing import Optional

from sqlmodel import Session

from app.models.entities import User
from shared.utils.exceptions import NotFoundError


def get_user_by_id(*, db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("user not found")
    return user


def update_user(
    *,
    db: Session,
    user_id: uuid.UUID,
    full_name: Optional[str],
    phone: Optional[str],
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("user not found")
    if full_name is not None:
        user.full_name = full_name
    if phone is not None:
        user.phone = phone
    db.commit()
    db.refresh(user)
    return user


__all__ = ["get_user_by_id", "update_user"]
