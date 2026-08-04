"""
Business logic for users service (module-level functions; facade via app/controller.py).
Todos los queries filtran por tenant_id explícito (RLS eliminado).
"""
from typing import Optional, List
from uuid import UUID
from sqlmodel import Session, or_, and_
from datetime import datetime

from app.models import User, AgentSetting, UserRequest
from app.schemas.user import UserCreate, UserUpdate
from app.schemas.request import UserRequestCreate

_PRIVILEGED_USER_FIELDS = ("is_staff", "is_superuser", "role_id", "permissions")


def create_user(*, db: Session, data: UserCreate, is_admin: bool = False) -> User:
    """Create a new user. Only an admin caller may set role_id/permissions."""
    payload = data.model_dump()
    if not is_admin:
        for field in _PRIVILEGED_USER_FIELDS:
            payload.pop(field, None)
    user = User(**payload)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(*, db: Session, user_id: UUID, tenant_id) -> Optional[User]:
    """Get user by ID (tenant-scoped)."""
    return db.query(User).filter(
        User.id == user_id,
        User.tenant_id == tenant_id
    ).first()


def get_user_by_email(*, db: Session, email: str, tenant_id) -> Optional[User]:
    return db.query(User).filter(
        User.email == email,
        User.tenant_id == tenant_id
    ).first()


def get_current_user(*, db: Session, user_id, tenant_id) -> Optional[User]:
    return get_user(db=db, user_id=user_id, tenant_id=tenant_id)


def list_users(*, db: Session, tenant_id, skip: int = 0, limit: int = 20,
               search: Optional[str] = None, is_active: Optional[bool] = None,
               is_superuser: Optional[bool] = None) -> tuple[List[User], int]:
    """List users with pagination and filtering (tenant-scoped)."""
    query = db.query(User).filter(User.tenant_id == tenant_id)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    if is_superuser is not None:
        if is_superuser:
            query = query.filter(
                or_(
                    User.is_superuser == True,
                    User.role_id == 1
                )
            )
        else:
            query = query.filter(
                and_(
                    User.is_superuser == False,
                    or_(User.role_id != 1, User.role_id.is_(None))
                )
            )

    if search:
        query = query.filter(
            or_(
                User.email.ilike(f"%{search}%"),
                User.first_name.ilike(f"%{search}%"),
                User.last_name.ilike(f"%{search}%"),
                User.npn.ilike(f"%{search}%")
            )
        )

    total = query.count()
    users = query.offset(skip).limit(limit).all()

    return users, total


def update_user(*, db: Session, user: User, data: UserUpdate, is_admin: bool = False) -> User:
    """Update user. Only an admin caller may change privileged fields."""
    update_data = data.model_dump(exclude_unset=True)
    update_data.pop("opt_in_notes", None)
    if not is_admin:
        for field in _PRIVILEGED_USER_FIELDS:
            update_data.pop(field, None)

    for key, value in update_data.items():
        if hasattr(User, key):
            setattr(user, key, value)

    user.modified_at = datetime.utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(*, db: Session, user: User) -> None:
    """Delete user (soft delete by setting is_active = False)."""
    user.is_active = False
    user.modified_at = datetime.utcnow()
    db.add(user)
    db.commit()


def get_user_stats(*, db: Session, tenant_id) -> dict:
    """Get aggregated user statistics (total, active, agents, opt-in count)."""
    total_users = db.query(User).filter(User.tenant_id == tenant_id).count() or 0
    active_users = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.is_active == True
    ).count() or 0
    agents = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.is_superuser == False,
        or_(User.role_id != 1, User.role_id.is_(None))
    ).count() or 0
    opt_in_users = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.accepted_campaign_terms_at.isnot(None)
    ).count() or 0
    return {
        "total_users": total_users,
        "active_users": active_users,
        "agents": agents,
        "opt_in_records": opt_in_users,
    }


# ---- Agent settings ----
def get_or_create_agent_settings(*, db: Session, user_id: UUID, tenant_id) -> AgentSetting:
    setting = db.query(AgentSetting).filter(
        AgentSetting.user_id == user_id,
        AgentSetting.tenant_id == tenant_id
    ).first()

    if not setting:
        setting = AgentSetting(user_id=user_id, tenant_id=tenant_id, settings={})
        db.add(setting)
        db.commit()
        db.refresh(setting)

    return setting


def update_agent_settings(*, db: Session, setting: AgentSetting,
                          new_settings: dict) -> AgentSetting:
    setting.settings = new_settings
    setting.modified_at = datetime.utcnow()
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


# ---- User requests ----
def create_user_request(*, db: Session, user_id: UUID, tenant_id,
                        data: UserRequestCreate, created_by_id: Optional[UUID] = None) -> UserRequest:
    request = UserRequest(
        user_id=user_id,
        tenant_id=tenant_id,
        request_type=data.request_type,
        data=data.data,
        created_by_id=created_by_id or user_id,
        notes=data.notes,
        status="pending",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def list_user_requests(*, db: Session, user_id: UUID, tenant_id,
                       request_type: Optional[str] = None, status: Optional[str] = None,
                       skip: int = 0, limit: int = 20) -> tuple[List[UserRequest], int]:
    query = db.query(UserRequest).filter(
        UserRequest.user_id == user_id,
        UserRequest.tenant_id == tenant_id
    )

    if request_type:
        query = query.filter(UserRequest.request_type == request_type)

    if status:
        query = query.filter(UserRequest.status == status)

    total = query.count()
    requests = query.order_by(UserRequest.created_at.desc()).offset(skip).limit(limit).all()

    return requests, total


def get_user_request(*, db: Session, request_id: UUID, user_id: UUID,
                     tenant_id) -> Optional[UserRequest]:
    return db.query(UserRequest).filter_by(
        id=request_id, user_id=user_id, tenant_id=tenant_id
    ).first()


def update_user_request(*, db: Session, request: UserRequest,
                        data: Optional[dict] = None, status: Optional[str] = None,
                        notes: Optional[str] = None,
                        reviewed_by_id: Optional[UUID] = None) -> UserRequest:
    if data:
        request.data = data
    if status:
        request.status = status
        if status in ["approved", "rejected"]:
            request.reviewed_at = datetime.utcnow()
    if notes:
        request.notes = notes
    if reviewed_by_id:
        request.reviewed_by_id = reviewed_by_id

    request.modified_at = datetime.utcnow()
    db.add(request)
    db.commit()
    db.refresh(request)
    return request
