from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.schemas.agent import AgentSettingResponse, AgentSettingUpdate
from app.schemas.calendar import (
    CalendarCreate, CalendarReminderItem, CalendarResponse, CalendarUpdate,
    PolicyWarningSyncRequest, PolicyWarningSyncResponse,
)
from app.schemas.request import (
    UserRequestCreate, UserRequestListResponse, UserRequestResponse, UserRequestUpdate,
)
from app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate
from app.schemas.webhook import AriaWebhookPayload
from shared.auth.dependencies import Identity, get_current_identity
from shared.db.engine import get_db

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _auth_header(request: Request) -> Optional[str]:
    return request.headers.get("authorization")


# ================= USERS =================
@router.post("/api/users", response_model=UserResponse, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings),
                identity: Identity = Depends(get_current_identity)) -> UserResponse:
    return controller.create_user(data=data, db=db, identity=identity)


@router.get("/api/users/me", response_model=UserResponse)
def me(db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
       identity: Identity = Depends(get_current_identity)) -> UserResponse:
    return controller.me(db=db, identity=identity)


@router.get("/api/users/stats")
def user_stats(db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings),
               identity: Identity = Depends(get_current_identity)) -> dict:
    return controller.user_stats(db=db, identity=identity)


@router.get("/api/users/{user_id}", response_model=UserResponse)
def get_user(user_id: UUID, db: Session = Depends(get_db),
             settings: Settings = Depends(get_settings),
             identity: Identity = Depends(get_current_identity)) -> UserResponse:
    return controller.get_user(user_id=user_id, db=db, identity=identity)


@router.get("/api/users", response_model=UserListResponse)
def list_users(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
               search: Optional[str] = Query(None), is_active: Optional[bool] = Query(None),
               is_superuser: Optional[str] = Query(None), db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings),
               identity: Identity = Depends(get_current_identity)) -> UserListResponse:
    return controller.list_users(page=page, size=size, search=search, is_active=is_active,
                                 is_superuser=is_superuser, db=db, identity=identity)


@router.put("/api/users/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, data: UserUpdate, db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings),
                identity: Identity = Depends(get_current_identity)) -> UserResponse:
    return controller.update_user(user_id=user_id, data=data, db=db, identity=identity)


@router.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: UUID, db: Session = Depends(get_db),
                settings: Settings = Depends(get_settings),
                identity: Identity = Depends(get_current_identity)) -> None:
    return controller.delete_user(user_id=user_id, db=db, identity=identity)


# ================= AGENT SETTINGS =================
@router.get("/api/users/{user_id}/agent-settings", response_model=AgentSettingResponse)
def get_agent_settings(user_id: UUID, db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings),
                       identity: Identity = Depends(get_current_identity)) -> AgentSettingResponse:
    return controller.get_agent_settings(user_id=user_id, db=db, identity=identity)


@router.put("/api/users/{user_id}/agent-settings", response_model=AgentSettingResponse)
def update_agent_settings(user_id: UUID, data: AgentSettingUpdate,
                          db: Session = Depends(get_db),
                          settings: Settings = Depends(get_settings),
                          identity: Identity = Depends(get_current_identity)) -> AgentSettingResponse:
    return controller.update_agent_settings(user_id=user_id, data=data, db=db, identity=identity)


# ================= USER REQUESTS =================
@router.post("/api/users/{user_id}/requests", response_model=UserRequestResponse, status_code=201)
def create_user_request(user_id: UUID, data: UserRequestCreate, db: Session = Depends(get_db),
                        settings: Settings = Depends(get_settings),
                        identity: Identity = Depends(get_current_identity)) -> UserRequestResponse:
    return controller.create_user_request(user_id=user_id, data=data, db=db, identity=identity)


@router.get("/api/users/{user_id}/requests", response_model=UserRequestListResponse)
def list_user_requests(user_id: UUID, request_type: Optional[str] = Query(None),
                       status: Optional[str] = Query(None), page: int = Query(1, ge=1),
                       size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings),
                       identity: Identity = Depends(get_current_identity)) -> UserRequestListResponse:
    return controller.list_user_requests(user_id=user_id, request_type=request_type,
                                         status=status, page=page, size=size,
                                         db=db, identity=identity)


@router.put("/api/users/{user_id}/requests/{request_id}", response_model=UserRequestResponse)
def update_user_request(user_id: UUID, request_id: UUID, data: UserRequestUpdate,
                        db: Session = Depends(get_db),
                        settings: Settings = Depends(get_settings),
                        identity: Identity = Depends(get_current_identity)) -> UserRequestResponse:
    return controller.update_user_request(user_id=user_id, request_id=request_id,
                                          data=data, db=db, identity=identity)


# ================= WEBHOOK ARIA (público: service-token via gateway) =================
@router.post("/api/saas/webhooks/aria")
def aria_webhook(payload: AriaWebhookPayload, db: Session = Depends(get_db),
                 settings: Settings = Depends(get_settings),
                 x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
                 authorization: Optional[str] = Header(None, alias="Authorization")) -> dict:
    return controller.handle_aria_webhook(payload=payload, db=db, settings=settings,
                                          x_api_key=x_api_key, authorization=authorization)


# ================= CALENDAR =================
@router.post("/api/calendar", response_model=CalendarResponse, status_code=201)
def create_calendar_event(data: CalendarCreate, request: Request, db: Session = Depends(get_db),
                          settings: Settings = Depends(get_settings),
                          identity: Identity = Depends(get_current_identity)) -> CalendarResponse:
    return controller.create_calendar_event(data=data, db=db, identity=identity,
                                            authorization=_auth_header(request))


@router.get("/api/calendar", response_model=List[CalendarResponse])
def list_calendar_events(start: Optional[datetime] = None, end: Optional[datetime] = None,
                         db: Session = Depends(get_db),
                         settings: Settings = Depends(get_settings),
                         identity: Identity = Depends(get_current_identity)) -> List[CalendarResponse]:
    return controller.list_calendar_events(start=start, end=end, db=db, identity=identity)


@router.put("/api/calendar/{event_id}", response_model=CalendarResponse)
def update_calendar_event(event_id: int, data: CalendarUpdate, request: Request,
                          db: Session = Depends(get_db),
                          settings: Settings = Depends(get_settings),
                          identity: Identity = Depends(get_current_identity)) -> CalendarResponse:
    return controller.update_calendar_event(event_id=event_id, data=data, db=db,
                                            identity=identity,
                                            authorization=_auth_header(request))


@router.delete("/api/calendar/{event_id}")
def delete_calendar_event(event_id: int, request: Request, db: Session = Depends(get_db),
                          settings: Settings = Depends(get_settings),
                          identity: Identity = Depends(get_current_identity)) -> dict:
    return controller.delete_calendar_event(event_id=event_id, db=db, identity=identity,
                                            authorization=_auth_header(request))


@router.get("/api/calendar/reminders/upcoming", response_model=List[CalendarReminderItem])
def upcoming_reminders(hours_ahead: int = 24, db: Session = Depends(get_db),
                       settings: Settings = Depends(get_settings),
                       identity: Identity = Depends(get_current_identity)) -> List[CalendarReminderItem]:
    return controller.calendar_reminders(hours_ahead=hours_ahead, db=db, identity=identity)


@router.post("/api/calendar/policy-warnings/sync", response_model=PolicyWarningSyncResponse)
def sync_policy_warnings(data: PolicyWarningSyncRequest, db: Session = Depends(get_db),
                         settings: Settings = Depends(get_settings),
                         identity: Identity = Depends(get_current_identity)) -> PolicyWarningSyncResponse:
    return controller.sync_policy_warnings(data=data, db=db, identity=identity)


# ================= GOOGLE CALENDAR =================
@router.get("/api/users/google/debug-calendar-events")
def google_debug(request: Request, settings: Settings = Depends(get_settings),
                 identity: Identity = Depends(get_current_identity)) -> dict:
    return controller.google_debug(authorization=_auth_header(request) or "", identity=identity)


@router.patch("/api/users/google/event-add-meet/{google_event_id}")
def google_add_meet(google_event_id: str, request: Request,
                    settings: Settings = Depends(get_settings),
                    identity: Identity = Depends(get_current_identity)) -> dict:
    return controller.google_add_meet(authorization=_auth_header(request) or "",
                                      identity=identity, google_event_id=google_event_id)


@router.get("/api/users/google/event-meet-link/{google_event_id}")
def google_meet_link(google_event_id: str, request: Request,
                     settings: Settings = Depends(get_settings),
                     identity: Identity = Depends(get_current_identity)) -> dict:
    return controller.google_meet_link(authorization=_auth_header(request) or "",
                                       identity=identity, google_event_id=google_event_id)


@router.delete("/api/users/google/calendar/{google_event_id}")
def google_delete_event(google_event_id: str, request: Request,
                        settings: Settings = Depends(get_settings),
                        identity: Identity = Depends(get_current_identity)) -> dict:
    return controller.google_delete_event(authorization=_auth_header(request) or "",
                                          identity=identity, google_event_id=google_event_id)


@router.post("/api/users/google/calendar/event")
def google_create_event_stub() -> None:
    """Stub heredado: crear eventos Google se hace via /api/calendar (local)."""
    from shared.utils.exceptions import AppError
    raise AppError(410, "Not implemented: create events through /api/calendar (local) or extend users-service")
