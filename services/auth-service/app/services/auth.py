"""
Auth Service Business Logic (module-level functions; facade via app/controller.py).
"""
from typing import Optional
from datetime import datetime, timedelta
import logging
import httpx

from sqlmodel import Session, select

from app.config import Settings
from app.models import User, RefreshToken, LoginAttempt
from app.schemas.user import UserRegister
from app.services.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    create_password_reset_token,
    verify_password_reset_token,
    decode_token,
    hash_token,
    create_service_token,
)
from shared.events.bus import EventBus
from shared.events.envelope import EventEnvelope
from shared.utils.exceptions import AppError, ConflictError

logger = logging.getLogger(__name__)


def login_user(*, db: Session, settings: Settings, email: str, password: str,
               platform: str = "desk", ip_address: Optional[str] = None,
               user_agent: Optional[str] = None) -> dict:
    """Authenticate and return tokens + user info (TokenResponse/LoginResponse shape)."""
    user = _authenticate(db, email, password)
    if not user:
        _log_login_attempt(db, email=email, ip_address=ip_address or "unknown",
                           success=False, failure_reason="invalid_credentials",
                           user_agent=user_agent)
        raise AppError(401, "Incorrect email or password")
    if not user.is_active:
        _log_login_attempt(db, email=email, ip_address=ip_address or "unknown",
                           success=False, failure_reason="inactive_user", user_agent=user_agent)
        raise AppError(403, "User account is inactive")

    tokens = _create_tokens(db, settings, user, platform=platform,
                            ip_address=ip_address, user_agent=user_agent)
    user.last_login = datetime.utcnow()
    db.add(user)
    db.commit()
    _log_login_attempt(db, email=email, ip_address=ip_address or "unknown",
                       success=True, user_agent=user_agent)
    tokens["user_id"] = str(user.id)
    tokens["email"] = user.email
    tokens["user"] = _user_dict(user)
    return tokens


def register_user(*, db: Session, settings: Settings, data: UserRegister,
                  event_bus: EventBus | None = None) -> User:
    """Create a user. Publishes `user.registered` on domain `auth` post-commit."""
    existing = db.exec(select(User).where(User.email == data.email)).first()
    if existing:
        raise ConflictError("email already registered")

    tenant_id = _resolve_tenant_id(data.email, settings)
    first_name, last_name = _split_full_name(data.full_name)
    user = User(
        email=data.email,
        password=get_password_hash(data.password),
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        role_id=None,
        is_active=True,
        date_joined=datetime.utcnow(),
        created_at=datetime.utcnow(),
        modified_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if event_bus is not None:
        event_bus.publish("auth", EventEnvelope(
            type="user.registered",
            aggregate_id=str(user.id),
            tenant_id=int(user.tenant_id) if str(user.tenant_id).isdigit() else None,
            payload={"email": user.email,
                     "full_name": f"{user.first_name or ''} {user.last_name or ''}".strip()},
        ))
    return user


def refresh_user_tokens(*, db: Session, settings: Settings, refresh_token: str,
                        platform: str = "desk", ip_address: Optional[str] = None,
                        user_agent: Optional[str] = None) -> dict:
    """Exchange a valid, unrevoked refresh token for a new access/refresh pair."""
    try:
        payload = decode_token(refresh_token)
    except ValueError:
        raise AppError(401, "Invalid refresh token")
    if payload.get("type") != "refresh":
        raise AppError(401, "Invalid refresh token")

    token_hash = hash_token(refresh_token)
    stored = db.exec(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).first()
    if not stored or stored.is_revoked or stored.expires_at < datetime.utcnow():
        raise AppError(401, "Refresh token is invalid, revoked, or expired")

    user = db.get(User, payload.get("sub"))
    if not user or not user.is_active:
        raise AppError(401, "User not found or inactive")

    stored.is_revoked = True
    db.add(stored)
    db.commit()

    tokens = _create_tokens(db, settings, user, platform=platform,
                            ip_address=ip_address, user_agent=user_agent)
    tokens["user_id"] = str(user.id)
    tokens["email"] = user.email
    return tokens


def revoke_refresh_token(*, db: Session, refresh_token: str) -> None:
    """Revoke a refresh token (logout). Silently no-ops if unknown/already revoked."""
    stored = db.exec(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
    ).first()
    if stored and not stored.is_revoked:
        stored.is_revoked = True
        db.add(stored)
        db.commit()


def issue_service_token(*, db: Session, settings: Settings, identity,
                        tenant_id: str, expires_minutes: int) -> dict:
    """Issue a service token bound to a tenant (staff/superuser only)."""
    if not identity.is_superuser and not identity.is_staff:
        raise AppError(403, "Forbidden")
    token = create_service_token(tenant_id, expires_minutes=expires_minutes)
    return {"token": token, "expires_in": expires_minutes * 60}


def reset_password_request(*, db: Session, settings: Settings, email: str) -> dict:
    """Request password reset. Always returns success to prevent email enumeration."""
    user = db.exec(select(User).where(User.email == email)).first()
    if user:
        reset_token = create_password_reset_token(str(user.id))
        user.password_recovery_token = reset_token
        db.add(user)
        db.commit()
        logger.warning(
            f"Password reset requested for {user.email} but no mailing service is "
            f"configured — token stored, email NOT sent."
        )
    return {"message": "Password reset email sent"}


def reset_password_confirm(*, db: Session, settings: Settings, token: str,
                           new_password: str) -> dict:
    """Confirm password reset."""
    user_id = verify_password_reset_token(token)
    user = db.get(User, user_id) if user_id else None
    if not user or user.password_recovery_token != token:
        raise AppError(400, "Invalid or expired token")
    user.password = get_password_hash(new_password)
    user.password_recovery_token = None
    user.first_login = False
    user.modified_at = datetime.utcnow()
    db.add(user)
    db.commit()
    return {"message": "Password has been reset successfully"}


def change_user_password(*, db: Session, settings: Settings, user: User,
                         old_password: str, new_password: str) -> dict:
    """Change user password (requires current password)."""
    if not verify_password(old_password, user.password):
        raise AppError(400, "Incorrect password")
    user.password = get_password_hash(new_password)
    user.password_recovery_token = None
    user.first_login = False
    user.modified_at = datetime.utcnow()
    db.add(user)
    db.commit()
    return {"message": "Password changed successfully"}


def get_current_user_info(*, db: Session, settings: Settings, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise AppError(404, "User not found")
    return user


def check_admin_status(*, db: Session, settings: Settings, user: User) -> dict:
    """Check if user has admin privileges."""
    is_admin = False
    permissions = []

    if user.role_id in [1, 2]:
        is_admin = True
        permissions.append("admin_role")

    if user.is_superuser:
        is_admin = True
        permissions.append("superuser")
    elif user.is_staff:
        is_admin = True
        permissions.append("staff")

    return {"isAdmin": is_admin, "permissions": permissions}


def validate_user_token(*, db: Session, settings: Settings, token: str) -> dict:
    """Validate a token and return user info (for inter-service communication)."""
    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return {"valid": False, "error": "Invalid token"}
        user = db.get(User, user_id)
        if not user or not user.is_active:
            return {"valid": False, "error": "User not found or inactive"}
        return {
            "valid": True,
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "role_id": user.role_id,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }
    except Exception as e:
        logger.warning(f"Token validation failed: {e}")
        return {"valid": False, "error": "Invalid or expired token"}


# ---- helpers ----
def _authenticate(db: Session, email: str, password: str) -> Optional[User]:
    user = db.exec(select(User).where(User.email == email)).first()
    if not user or not user.password:
        return None
    if not verify_password(password, user.password):
        return None
    return user


def _create_tokens(db: Session, settings: Settings, user: User, *, platform: str,
                   ip_address: Optional[str], user_agent: Optional[str]) -> dict:
    tenant_id = str(getattr(user, "tenant_id", "") or "")
    access_token = create_access_token(
        user_id=str(user.id),
        tenant_id=tenant_id,
        email=user.email,
        platform=platform,
        role_id=user.role_id,
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    refresh_token = create_refresh_token(user_id=str(user.id), tenant_id=tenant_id)
    db.add(RefreshToken(
        user_id=user.id,
        tenant_id=tenant_id,
        token_hash=hash_token(refresh_token),
        device_info=(user_agent[:255] if user_agent else None),
        ip_address=ip_address,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    db.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def _log_login_attempt(db: Session, *, email: str, ip_address: str, success: bool,
                       failure_reason: Optional[str] = None,
                       user_agent: Optional[str] = None) -> None:
    db.add(LoginAttempt(
        email=email,
        ip_address=ip_address,
        success=success,
        failure_reason=failure_reason,
        user_agent=user_agent[:500] if user_agent else None,
    ))
    db.commit()


def _resolve_tenant_id(email: str, settings: Settings) -> str:
    """Resolve tenant_id via tenant-service using user email."""
    if not email:
        raise AppError(400, "Email required to resolve tenant")
    url = f"{settings.TENANT_SERVICE_URL}/api/resolve/email"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, params={"email": email})
            if resp.status_code == 404:
                raise AppError(404, "Tenant not found for user email")
            resp.raise_for_status()
            data = resp.json()
            tenant_id = data.get("id")
            if not tenant_id:
                raise AppError(400, "Tenant resolution missing id")
            return tenant_id
    except AppError:
        raise
    except Exception as e:
        raise AppError(400, f"Failed to resolve tenant: {e}")


def _split_full_name(full_name: str) -> tuple[Optional[str], Optional[str]]:
    parts = (full_name or "").strip().split(" ", 1)
    first = parts[0] or None
    last = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return first, last


def _user_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "tenant_id": str(user.tenant_id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "role_id": user.role_id,
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "first_login": user.first_login,
    }
