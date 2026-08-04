"""
Auth controller (FACADE): orquesta app/services/*, traduce a schemas.
Un método por endpoint; recibe deps como parámetros (no lee Request).
"""
from typing import Optional
from uuid import UUID

from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.models import User
from app.schemas.auth import (
    LoginRequest, MessageResponse, PasswordChangeRequest, PasswordResetConfirm,
    PasswordResetRequest, RefreshRequest, ServiceTokenRequest, ServiceTokenResponse,
    TokenResponse, TokenValidateRequest, AdminCheckResponse,
)
from app.schemas.google import GoogleAccessTokenResponse, GoogleAuthUrlResponse, GoogleStatusResponse
from app.schemas.user import LoginResponse, UserRegister, UserResponse
from app.serializers.user import user_to_response
from app.services import auth as auth_service
from app.services import google_oauth as google_service
from app.services.security import decode_token
from shared.auth.dependencies import Identity
from shared.events.bus import EventBus
from shared.utils.exceptions import AppError


def login(*, data: LoginRequest, db: Session, settings) -> LoginResponse:
    tokens = auth_service.login_user(
        db=db, settings=settings, email=data.email, password=data.password,
        platform=(data.platform or "desk").lower(),
    )
    user = tokens.pop("user")
    tokens["access"] = tokens["access_token"]
    tokens["token"] = tokens["access_token"]
    tokens["refresh"] = tokens["refresh_token"]
    tokens["user"] = user
    return LoginResponse(**tokens)


def token(*, form: OAuth2PasswordRequestForm, db: Session, settings) -> TokenResponse:
    platform = form.platform if hasattr(form, "platform") else "desk"
    tokens = auth_service.login_user(
        db=db, settings=settings, email=form.username, password=form.password,
        platform=str(platform or "desk").lower(),
    )
    tokens.pop("user", None)
    return TokenResponse(**tokens)


def register(*, data: UserRegister, db: Session, settings,
             event_bus: EventBus) -> UserResponse:
    user = auth_service.register_user(db=db, settings=settings, data=data,
                                      event_bus=event_bus)
    db.commit()
    db.refresh(user)
    return user_to_response(user)


def refresh(*, data: RefreshRequest, db: Session, settings) -> TokenResponse:
    tokens = auth_service.refresh_user_tokens(
        db=db, settings=settings, refresh_token=data.refresh_token,
        platform=(data.platform or "desk").lower(),
    )
    tokens.pop("user", None)
    return TokenResponse(**tokens)


def logout(*, data: RefreshRequest, db: Session, settings) -> MessageResponse:
    auth_service.revoke_refresh_token(db=db, refresh_token=data.refresh_token)
    return MessageResponse(message="Logged out")


def service_token(*, data: ServiceTokenRequest, db: Session, settings,
                  identity: Identity) -> ServiceTokenResponse:
    resp = auth_service.issue_service_token(
        db=db, settings=settings, identity=identity,
        tenant_id=data.tenant_id, expires_minutes=data.expires_minutes)
    return ServiceTokenResponse(**resp)


def reset_password(*, data: PasswordResetRequest, db: Session, settings) -> MessageResponse:
    resp = auth_service.reset_password_request(db=db, settings=settings, email=data.email)
    return MessageResponse(**resp)


def reset_password_confirm(*, data: PasswordResetConfirm, db: Session,
                           settings) -> MessageResponse:
    resp = auth_service.reset_password_confirm(
        db=db, settings=settings, token=data.token, new_password=data.new_password)
    return MessageResponse(**resp)


def change_password(*, data: PasswordChangeRequest, db: Session, settings,
                    user_id: str) -> MessageResponse:
    user = auth_service.get_current_user_info(db=db, settings=settings, user_id=user_id)
    resp = auth_service.change_user_password(
        db=db, settings=settings, user=user,
        old_password=data.old_password, new_password=data.new_password)
    return MessageResponse(**resp)


def me(*, db: Session, settings, user_id: str) -> UserResponse:
    user = auth_service.get_current_user_info(db=db, settings=settings, user_id=user_id)
    return user_to_response(user)


def check_admin(*, db: Session, settings, user_id: str) -> AdminCheckResponse:
    user = auth_service.get_current_user_info(db=db, settings=settings, user_id=user_id)
    resp = auth_service.check_admin_status(db=db, settings=settings, user=user)
    return AdminCheckResponse(**resp)


def validate_token(*, data: TokenValidateRequest, db: Session, settings) -> dict:
    return auth_service.validate_user_token(db=db, settings=settings, token=data.token)


# ---- Google OAuth ----
# Los endpoints google son PÚBLICOS (popup OAuth); la identidad se verifica
# con el Bearer token del cliente + header X-Tenant-Id (comportamiento heredado).

def _google_user_and_tenant(request, db: Session):
    """Verifica Authorization Bearer + X-Tenant-Id y devuelve (user, tenant_id)."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AppError(401, "Authorization required")
    token = auth.split(" ", 1)[1].strip()
    try:
        claims = decode_token(token)
    except Exception as e:
        raise AppError(401, f"Invalid token: {e}")
    sub = claims.get("sub")
    if not sub:
        raise AppError(401, "Token missing sub")
    try:
        user_id = UUID(str(sub))
    except Exception:
        raise AppError(401, "Token sub must be UUID")
    tenant_raw = request.headers.get("x-tenant-id", "")
    if not tenant_raw:
        raise AppError(400, "X-Tenant-Id required")
    try:
        tenant_id = UUID(tenant_raw)
    except Exception:
        raise AppError(400, "Invalid X-Tenant-Id")
    user = db.get(User, user_id)
    if not user:
        raise AppError(401, "User not found")
    if not user.is_active:
        raise AppError(403, "User is inactive")
    return user, tenant_id


def google_check_config(*, settings) -> dict:
    return google_service.check_config()


def google_status(*, request, db: Session, settings) -> GoogleStatusResponse:
    user, tenant_id = _google_user_and_tenant(request, db)
    resp = google_service.get_status(db=db, user=user, tenant_id=tenant_id)
    return GoogleStatusResponse(**resp)


def google_auth_url(*, request, db: Session, settings,
                    redirect_uri: Optional[str]) -> GoogleAuthUrlResponse:
    user, tenant_id = _google_user_and_tenant(request, db)
    resp = google_service.get_auth_url(
        request=request, db=db, redirect_uri=redirect_uri,
        user=user, tenant_id=tenant_id)
    return GoogleAuthUrlResponse(**resp)


def google_callback(*, request, db: Session, settings, code, state, error,
                    redirect_uri) -> HTMLResponse:
    result = google_service.handle_callback(
        request=request, db=db, code=code, state=state, error=error,
        redirect_uri=redirect_uri)
    return HTMLResponse(content=result["html"])


def google_disconnect(*, request, db: Session, settings) -> dict:
    user, tenant_id = _google_user_and_tenant(request, db)
    return google_service.disconnect(db=db, user=user, tenant_id=tenant_id)


def google_access_token(*, request, db: Session, settings) -> GoogleAccessTokenResponse:
    user, tenant_id = _google_user_and_tenant(request, db)
    resp = google_service.get_access_token(db=db, user=user, tenant_id=tenant_id)
    return GoogleAccessTokenResponse(**resp)
