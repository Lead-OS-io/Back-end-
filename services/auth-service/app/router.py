from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app import controller
from app.config import Settings
from app.schemas.auth import (
    LoginRequest, MessageResponse, PasswordChangeRequest, PasswordResetConfirm,
    PasswordResetRequest, RefreshRequest, ServiceTokenRequest, ServiceTokenResponse,
    TokenResponse, TokenValidateRequest, AdminCheckResponse,
)
from app.schemas.google import GoogleAccessTokenResponse, GoogleAuthUrlResponse, GoogleStatusResponse
from app.schemas.user import LoginResponse, UserRegister, UserResponse
from shared.auth.dependencies import Identity, get_current_identity
from shared.db.engine import get_db
from shared.events.bus import EventBus

router = APIRouter()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


@router.post("/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db),
          settings=Depends(get_settings)) -> LoginResponse:
    return controller.login(data=data, db=db, settings=settings)


@router.post("/login/", response_model=LoginResponse, include_in_schema=False)
def login_alias(data: LoginRequest, db: Session = Depends(get_db),
                settings=Depends(get_settings)) -> LoginResponse:
    return controller.login(data=data, db=db, settings=settings)


@router.post("/token", response_model=TokenResponse)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db),
          settings=Depends(get_settings)) -> TokenResponse:
    return controller.token(form=form, db=db, settings=settings)


@router.post("/register", response_model=UserResponse, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db),
             settings=Depends(get_settings),
             event_bus: EventBus = Depends(get_event_bus)) -> UserResponse:
    return controller.register(data=data, db=db, settings=settings, event_bus=event_bus)


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest, db: Session = Depends(get_db),
            settings=Depends(get_settings)) -> TokenResponse:
    return controller.refresh(data=data, db=db, settings=settings)


@router.post("/logout", response_model=MessageResponse)
def logout(data: RefreshRequest, db: Session = Depends(get_db),
           settings=Depends(get_settings)) -> MessageResponse:
    return controller.logout(data=data, db=db, settings=settings)


@router.post("/service-token", response_model=ServiceTokenResponse)
def service_token(data: ServiceTokenRequest, db: Session = Depends(get_db),
                  settings=Depends(get_settings),
                  identity: Identity = Depends(get_current_identity)) -> ServiceTokenResponse:
    return controller.service_token(data=data, db=db, settings=settings, identity=identity)


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(data: PasswordResetRequest, db: Session = Depends(get_db),
                   settings=Depends(get_settings)) -> MessageResponse:
    return controller.reset_password(data=data, db=db, settings=settings)


@router.post("/reset-password-confirm", response_model=MessageResponse)
def reset_password_confirm(data: PasswordResetConfirm, db: Session = Depends(get_db),
                           settings=Depends(get_settings)) -> MessageResponse:
    return controller.reset_password_confirm(data=data, db=db, settings=settings)


@router.post("/change-password", response_model=MessageResponse)
def change_password(data: PasswordChangeRequest, db: Session = Depends(get_db),
                    settings=Depends(get_settings),
                    identity: Identity = Depends(get_current_identity)) -> MessageResponse:
    return controller.change_password(data=data, db=db, settings=settings,
                                      user_id=str(identity.user_id))


@router.get("/me", response_model=UserResponse)
def me(db: Session = Depends(get_db), settings=Depends(get_settings),
       identity: Identity = Depends(get_current_identity)) -> UserResponse:
    return controller.me(db=db, settings=settings, user_id=str(identity.user_id))


@router.get("/check-admin", response_model=AdminCheckResponse)
def check_admin(db: Session = Depends(get_db), settings=Depends(get_settings),
                identity: Identity = Depends(get_current_identity)) -> AdminCheckResponse:
    return controller.check_admin(db=db, settings=settings, user_id=str(identity.user_id))


@router.post("/validate-token")
def validate_token(data: TokenValidateRequest, db: Session = Depends(get_db),
                   settings=Depends(get_settings)) -> dict:
    return controller.validate_token(data=data, db=db, settings=settings)


# ---- Google OAuth (público: popup; auth vía Bearer + X-Tenant-Id heredado) ----
@router.get("/google/check-config")
def google_check_config(settings=Depends(get_settings)) -> dict:
    return controller.google_check_config(settings=settings)


@router.get("/google/status", response_model=GoogleStatusResponse)
def google_status(request: Request, db: Session = Depends(get_db),
                  settings=Depends(get_settings)) -> GoogleStatusResponse:
    return controller.google_status(request=request, db=db, settings=settings)


@router.get("/google/auth-url", response_model=GoogleAuthUrlResponse)
def google_auth_url(request: Request, redirect_uri: Optional[str] = Query(None),
                    db: Session = Depends(get_db),
                    settings=Depends(get_settings)) -> GoogleAuthUrlResponse:
    return controller.google_auth_url(request=request, db=db, settings=settings,
                                      redirect_uri=redirect_uri)


@router.get("/google/callback", response_class=HTMLResponse)
def google_callback(request: Request, code: Optional[str] = Query(None),
                    state: Optional[str] = Query(None), error: Optional[str] = Query(None),
                    redirect_uri: Optional[str] = Query(None),
                    db: Session = Depends(get_db),
                    settings=Depends(get_settings)) -> HTMLResponse:
    return controller.google_callback(request=request, db=db, settings=settings,
                                      code=code, state=state, error=error,
                                      redirect_uri=redirect_uri)


@router.post("/google/disconnect")
def google_disconnect(request: Request, db: Session = Depends(get_db),
                      settings=Depends(get_settings)) -> dict:
    return controller.google_disconnect(request=request, db=db, settings=settings)


@router.get("/google/access-token", response_model=GoogleAccessTokenResponse)
def google_access_token(request: Request, db: Session = Depends(get_db),
                        settings=Depends(get_settings)) -> GoogleAccessTokenResponse:
    return controller.google_access_token(request=request, db=db, settings=settings)
