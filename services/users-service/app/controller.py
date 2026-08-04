"""
Users controller (FACADE): orquesta app/services/*, traduce a schemas.
Un método por endpoint; recibe deps como parámetros (no lee Request).
Los endpoints que sincronizan con Google reciben el Authorization header como string.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlmodel import Session

from app.schemas.calendar import (
    CalendarCreate, CalendarReminderItem, CalendarResponse, CalendarUpdate,
)
from app.schemas.request import (
    UserRequestCreate, UserRequestListResponse, UserRequestResponse, UserRequestUpdate,
)
from app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate
from app.serializers.user import (
    user_request_to_response, user_to_response,
)
from app.services import calendar as calendar_service
from app.services import users as users_service
from shared.utils.exceptions import AppError


def _is_admin(identity) -> bool:
    return identity.is_superuser or identity.role_id == 1


def _can_access_user(identity, user_id: UUID) -> bool:
    return _is_admin(identity) or str(identity.user_id) == str(user_id)


# ---- Users ----
def create_user(*, data: UserCreate, db: Session, identity) -> UserResponse:
    if str(data.tenant_id) != str(identity.tenant_id):
        raise AppError(400, "Tenant ID mismatch")
    existing = users_service.get_user_by_email(db=db, email=data.email,
                                               tenant_id=identity.tenant_id)
    if existing:
        raise AppError(400, "Email already registered")
    user = users_service.create_user(db=db, data=data, is_admin=_is_admin(identity))
    return user_to_response(user)


def get_user(*, user_id: UUID, db: Session, identity) -> UserResponse:
    if not _can_access_user(identity, user_id):
        raise AppError(403, "Cannot access this user")
    user = users_service.get_user(db=db, user_id=user_id, tenant_id=identity.tenant_id)
    if not user:
        raise AppError(404, "User not found")
    return user_to_response(user)


def me(*, db: Session, identity) -> UserResponse:
    user = users_service.get_current_user(db=db, user_id=identity.user_id,
                                          tenant_id=identity.tenant_id)
    if not user:
        raise AppError(404, "User not found")
    return user_to_response(user)


def list_users(*, page: int, size: int, search: Optional[str], is_active: Optional[bool],
               is_superuser: Optional[str], db: Session, identity) -> UserListResponse:
    is_superuser_bool = None
    if is_superuser is not None:
        if is_superuser.lower() in ("true", "super_admin"):
            is_superuser_bool = True
        elif is_superuser.lower() in ("false", "agent"):
            is_superuser_bool = False

    users, total = users_service.list_users(
        db=db, tenant_id=identity.tenant_id, skip=(page - 1) * size, limit=size,
        search=search, is_active=is_active, is_superuser=is_superuser_bool)
    return UserListResponse(items=[user_to_response(u) for u in users], total=total,
                            page=page, size=size,
                            pages=(total + size - 1) // size if total > 0 else 0)


def update_user(*, user_id: UUID, data: UserUpdate, db: Session, identity) -> UserResponse:
    if not _can_access_user(identity, user_id):
        raise AppError(403, "Cannot access this user")
    user = users_service.get_user(db=db, user_id=user_id, tenant_id=identity.tenant_id)
    if not user:
        raise AppError(404, "User not found")
    updated = users_service.update_user(db=db, user=user, data=data,
                                        is_admin=_is_admin(identity))
    return user_to_response(updated)


def delete_user(*, user_id: UUID, db: Session, identity) -> None:
    if not _can_access_user(identity, user_id):
        raise AppError(403, "Cannot access this user")
    user = users_service.get_user(db=db, user_id=user_id, tenant_id=identity.tenant_id)
    if not user:
        raise AppError(404, "User not found")
    users_service.delete_user(db=db, user=user)


def user_stats(*, db: Session, identity) -> dict:
    return users_service.get_user_stats(db=db, tenant_id=identity.tenant_id)


# ---- User requests ----
def create_user_request(*, user_id: UUID, data: UserRequestCreate, db: Session,
                        identity) -> UserRequestResponse:
    user = users_service.get_user(db=db, user_id=user_id, tenant_id=identity.tenant_id)
    if not user:
        raise AppError(404, "User not found")
    created_by_id = UUID(str(identity.user_id)) if str(identity.user_id) != str(user_id) else user_id
    request = users_service.create_user_request(
        db=db, user_id=user_id, tenant_id=identity.tenant_id, data=data,
        created_by_id=created_by_id)
    return user_request_to_response(request)


def list_user_requests(*, user_id: UUID, request_type: Optional[str], status: Optional[str],
                       page: int, size: int, db: Session, identity) -> UserRequestListResponse:
    user = users_service.get_user(db=db, user_id=user_id, tenant_id=identity.tenant_id)
    if not user:
        raise AppError(404, "User not found")
    requests, total = users_service.list_user_requests(
        db=db, user_id=user_id, tenant_id=identity.tenant_id,
        request_type=request_type, status=status, skip=(page - 1) * size, limit=size)
    return UserRequestListResponse(items=[user_request_to_response(r) for r in requests],
                                   total=total, page=page, size=size)


def update_user_request(*, user_id: UUID, request_id: UUID, data: UserRequestUpdate,
                        db: Session, identity) -> UserRequestResponse:
    user = users_service.get_user(db=db, user_id=user_id, tenant_id=identity.tenant_id)
    if not user:
        raise AppError(404, "User not found")
    request = users_service.get_user_request(db=db, request_id=request_id, user_id=user_id,
                                             tenant_id=identity.tenant_id)
    if not request:
        raise AppError(404, "Request not found")

    reviewed_by_id = None
    if data.status in ["approved", "rejected"]:
        reviewed_by_id = UUID(str(identity.user_id))

    updated = users_service.update_user_request(
        db=db, request=request, data=data.data, status=data.status,
        notes=data.notes, reviewed_by_id=reviewed_by_id)
    return user_request_to_response(updated)


# ---- Calendar ----
def create_calendar_event(*, data: CalendarCreate, db: Session, identity,
                          authorization: Optional[str]) -> CalendarResponse:
    ev = calendar_service.create_event(
        db=db, payload=data, tenant_id=identity.tenant_id, user_id=identity.user_id,
        authorization=authorization)
    return CalendarResponse.model_validate(ev, from_attributes=True)


def list_calendar_events(*, start: Optional[datetime], end: Optional[datetime],
                         db: Session, identity) -> List[CalendarResponse]:
    events = calendar_service.list_events(
        db=db, tenant_id=identity.tenant_id, user_id=identity.user_id, start=start, end=end)
    return [CalendarResponse.model_validate(e, from_attributes=True) for e in events]


def update_calendar_event(*, event_id: int, data: CalendarUpdate, db: Session,
                          identity, authorization: Optional[str]) -> CalendarResponse:
    ev = calendar_service.update_event(
        db=db, payload=data, tenant_id=identity.tenant_id, user_id=identity.user_id,
        event_id=event_id, authorization=authorization)
    return CalendarResponse.model_validate(ev, from_attributes=True)


def delete_calendar_event(*, event_id: int, db: Session, identity,
                          authorization: Optional[str]) -> dict:
    return calendar_service.delete_event(
        db=db, tenant_id=identity.tenant_id, user_id=identity.user_id,
        event_id=event_id, authorization=authorization)


def calendar_reminders(*, hours_ahead: int, db: Session,
                       identity) -> List[CalendarReminderItem]:
    return calendar_service.upcoming_reminders(
        db=db, tenant_id=identity.tenant_id, user_id=identity.user_id,
        hours_ahead=hours_ahead)


# ---- Google calendar ----
def google_debug(*, authorization: str, identity) -> dict:
    return calendar_service.debug_calendar_events(authorization=authorization,
                                                  tenant_id=identity.tenant_id)


def google_add_meet(*, authorization: str, identity, google_event_id: str) -> dict:
    return calendar_service.add_meet_link(authorization=authorization,
                                          tenant_id=identity.tenant_id,
                                          google_event_id=google_event_id)


def google_meet_link(*, authorization: str, identity, google_event_id: str) -> dict:
    return calendar_service.get_meet_link(authorization=authorization,
                                          tenant_id=identity.tenant_id,
                                          google_event_id=google_event_id)


def google_delete_event(*, authorization: str, identity, google_event_id: str) -> dict:
    return calendar_service.delete_google_event(authorization=authorization,
                                                tenant_id=identity.tenant_id,
                                                google_event_id=google_event_id)
