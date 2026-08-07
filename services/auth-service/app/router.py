import json
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.schemas.auth import LoginRequest
from app.schemas.onboarding import OnboardingAcceptedResponse, OnboardingRequest
from app.schemas.user import UserUpdateRequest
from shared.db.engine import get_db
from shared.events.bus import EventBus
from shared.utils.exceptions import AppError

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def _refresh_cookie(request: Request) -> Optional[str]:
    return request.cookies.get("refresh_token")


def _authorization(request: Request) -> Optional[str]:
    return request.headers.get("authorization")


def _with_set_cookie(payload: dict, response: Response,
                     status_code: int = 200) -> JSONResponse:
    """Build a JSONResponse that carries the Set-Cookie headers from `response`."""
    json_resp = JSONResponse(content=payload, status_code=status_code)
    for key, value in response.headers.items():
        if key.lower() == "set-cookie":
            json_resp.headers[key] = value
    return json_resp


@router.post(
    "/onboarding",
    response_model=OnboardingAcceptedResponse,
    status_code=202,
)
def onboarding(
    data: OnboardingRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    event_bus: EventBus = Depends(get_event_bus),
):
    return controller.onboarding(data=data, db=db, settings=settings, event_bus=event_bus)


@router.post("/login")
def login_endpoint(
    data: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    event_bus: EventBus = Depends(get_event_bus),
    request: Request = ...,
):
    upstream_response = Response()
    payload = controller.login(
        data=data, settings=settings, db=db,
        event_bus=event_bus, response=upstream_response, request=request,
    )
    return _with_set_cookie(payload, upstream_response)


@router.post("/logout")
def logout_endpoint(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    cookie_token: Optional[str] = Depends(_refresh_cookie),
):
    upstream_response = Response()
    controller.logout(settings=settings, db=db, response=upstream_response, cookie_token=cookie_token)
    return _with_set_cookie({}, upstream_response, status_code=204)


@router.post("/refresh")
def refresh_endpoint(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    cookie_token: Optional[str] = Depends(_refresh_cookie),
    request: Request = ...,
):
    upstream_response = Response()
    payload = controller.refresh(
        settings=settings, db=db, response=upstream_response,
        cookie_token=cookie_token, request=request,
    )
    return _with_set_cookie(payload, upstream_response)


@router.get("/validate")
def validate_endpoint(
    settings: Settings = Depends(get_settings),
    authorization: Optional[str] = Depends(_authorization),
):
    return controller.validate(settings=settings, authorization=authorization)


@router.get("/me")
def get_me_endpoint(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    authorization: Optional[str] = Depends(_authorization),
):
    return controller.get_me(settings=settings, db=db, authorization=authorization)


@router.patch("/me")
def patch_me_endpoint(
    data: UserUpdateRequest,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    authorization: Optional[str] = Depends(_authorization),
):
    return controller.patch_me(
        data=data, settings=settings, db=db,
        event_bus=event_bus, authorization=authorization,
    )
