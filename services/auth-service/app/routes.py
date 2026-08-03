"""
Auth Service API Routes.
"""
from datetime import datetime
from typing import Optional
import logging
import time
from collections import defaultdict
from sqlalchemy import text

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlmodel import Session
from pydantic import BaseModel

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    PasswordResetRequest,
    PasswordResetConfirm,
    PasswordChangeRequest,
    TokenResponse,
    LoginResponse,
    UserResponse,
    AdminCheckResponse,
    MessageResponse,
    ServiceTokenRequest,
    ServiceTokenResponse,
    HealthResponse,
    RefreshTokenRequest,
)
from app.services import AuthService
from app.security import decode_token, create_service_token
from app.google_routes import router as google_router

router = APIRouter()
router.include_router(google_router)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


# Rate limiter
# ponytail: in-memory, per-process — fine at 1 uvicorn worker; move to Redis if workers > 1
class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
    
    def is_allowed(self, key: str, limit: int, window: int) -> bool:
        now = time.time()
        self.requests[key] = [t for t in self.requests[key] if now - t < window]
        
        if len(self.requests[key]) >= limit:
            return False
        
        self.requests[key].append(now)
        return True


rate_limiter = RateLimiter()


def _is_aria_tenant_user(db: Session, user: User) -> bool:
    tenant_slug = (settings.ARIA_TENANT_SLUG or "aria").strip().lower()
    row = db.execute(
        text("SELECT id FROM public.tenants WHERE lower(slug)=:slug LIMIT 1"),
        {"slug": tenant_slug},
    ).first()
    if not row:
        return False
    aria_tenant_id = str(row[0])
    return str(user.tenant_id) == aria_tenant_id


def _blocked_subscription_response(detail: str, code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"message": detail, "code": code},
    )


def _validate_aria_subscription_or_raise(db: Session, user: User) -> None:
    if not _is_aria_tenant_user(db, user):
        return
    row = db.execute(
        text(
            """
            SELECT
                access_status,
                subscription_status,
                subscription_is_active,
                next_payment,
                last_event_type
            FROM public.aria_subscription_states
            WHERE tenant_id=:tenant_id AND lower(user_email)=:email
            LIMIT 1
            """
        ),
        {"tenant_id": str(user.tenant_id), "email": (user.email or "").lower()},
    ).first()
    if not row:
        raise _blocked_subscription_response(
            "We could not validate your subscription. Please contact support.",
            "SUBSCRIPTION_VALIDATION_ERROR",
        )
    access_status, subscription_status, subscription_is_active, next_payment, last_event_type = row
    access_status = (access_status or "").strip().lower()
    subscription_status = (subscription_status or "").strip().lower()
    event_type = (last_event_type or "").strip().upper()
    now = datetime.utcnow()
    if event_type in {"PAYMENT_FAILED", "SUBSCRIPTION_CANCELLED"}:
        raise _blocked_subscription_response(
            "Your subscription payment is overdue. Please update your billing information.",
            "SUBSCRIPTION_PAST_DUE",
        )
    if next_payment and next_payment < now and subscription_status not in {"success", "active", "trial", "trialing"}:
        raise _blocked_subscription_response(
            "Your subscription payment is overdue. Please update your billing information.",
            "SUBSCRIPTION_PAST_DUE",
        )
    if access_status != "active" or subscription_is_active is False:
        raise _blocked_subscription_response(
            "Your subscription is inactive. Please contact support.",
            "SUBSCRIPTION_INACTIVE",
        )


# Dependencies
async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Get current user from JWT token."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = decode_token(token)
        # Only an access token may authenticate a user - a refresh/service/reset
        # token that happens to decode with the same key must not stand in for one.
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    return user


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Get current user if authenticated, otherwise None."""
    if not token:
        return None
    
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


# Health check
@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service=settings.SERVICE_NAME,
        version=settings.SERVICE_VERSION,
    )


# OAuth2 token endpoint
@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 compatible token endpoint."""
    client_ip = request.client.host if request.client else "unknown"
    platform = (request.headers.get("x-platform") or request.headers.get("x-system-origin") or "").lower()
    if not platform:
        try:
            # Leer plataforma desde el formulario (p.ej. platform=desk|hub|nest)
            form_body = await request.form()
            platform = str(form_body.get("platform") or "").lower()
        except Exception:
            platform = ""
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing platform claim (desk|hub|nest)",
        )
    
    # Rate limiting
    if not rate_limiter.is_allowed(f"login:{client_ip}", settings.RATE_LIMIT_LOGIN, 60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )
    
    auth_service = AuthService(db)
    user = auth_service.authenticate_user(form_data.username, form_data.password)
    
    if not user:
        auth_service.log_login_attempt(
            email=form_data.username,
            ip_address=client_ip,
            success=False,
            failure_reason="invalid_credentials",
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        auth_service.log_login_attempt(
            email=form_data.username,
            ip_address=client_ip,
            success=False,
            failure_reason="inactive_user",
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    _validate_aria_subscription_or_raise(db, user)
    
    # Create tokens
    try:
        tokens = auth_service.create_tokens(
            user,
            platform=platform,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        auth_service.log_login_attempt(
            email=form_data.username,
            ip_address=client_ip,
            success=False,
            failure_reason="tenant_resolution_failed",
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    auth_service.update_last_login(user)
    
    auth_service.log_login_attempt(
        email=form_data.username,
        ip_address=client_ip,
        success=True,
        user_agent=request.headers.get("user-agent"),
    )
    
    redirect_url = f"https://aria-desk.com/first-check?email={user.email}" if user.first_login else None
    
    return TokenResponse(
        access_token=tokens["access_token"],
        expires_in=tokens["expires_in"],
        refresh_token=tokens["refresh_token"],
        user_id=str(user.id),
        email=user.email,
        redirect_url=redirect_url,
    )


# Login endpoint (JSON body)
@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
    db: Session = Depends(get_db),
):
    """Login with email and password."""
    client_ip = request.client.host if request.client else "unknown"
    platform = (request.headers.get("x-platform") or request.headers.get("x-system-origin") or "").lower()
    if not platform:
        platform = (login_data.platform or "").lower() if hasattr(login_data, "platform") else ""
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing platform claim (desk|hub|nest)",
        )
    
    # Rate limiting
    if not rate_limiter.is_allowed(f"login:{client_ip}", settings.RATE_LIMIT_LOGIN, 60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
        )
    
    auth_service = AuthService(db)
    user = auth_service.authenticate_user(login_data.email, login_data.password)
    
    if not user:
        auth_service.log_login_attempt(
            email=login_data.email,
            ip_address=client_ip,
            success=False,
            failure_reason="invalid_credentials",
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    if not user.is_active:
        auth_service.log_login_attempt(
            email=login_data.email,
            ip_address=client_ip,
            success=False,
            failure_reason="inactive_user",
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
    _validate_aria_subscription_or_raise(db, user)
    
    # Create tokens
    try:
        tokens = auth_service.create_tokens(
            user,
            platform=platform,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        auth_service.log_login_attempt(
            email=login_data.email,
            ip_address=client_ip,
            success=False,
            failure_reason="tenant_resolution_failed",
            user_agent=request.headers.get("user-agent"),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    auth_service.update_last_login(user)
    
    auth_service.log_login_attempt(
        email=login_data.email,
        ip_address=client_ip,
        success=True,
        user_agent=request.headers.get("user-agent"),
    )
    
    user_response = UserResponse.model_validate(user.model_dump())
    redirect_url = f"https://aria-desk.com/first-check?email={user.email}" if user.first_login else None
    
    return LoginResponse(
        access_token=tokens["access_token"],
        access=tokens["access_token"],
        token=tokens["access_token"],
        refresh=tokens["refresh_token"],
        expires_in=tokens["expires_in"],
        user=user_response,
        redirect_url=redirect_url,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    request: Request,
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """Exchange a refresh token for a new access/refresh token pair (rotates the old one)."""
    client_ip = request.client.host if request.client else "unknown"
    platform = (request.headers.get("x-platform") or request.headers.get("x-system-origin") or "").lower()
    if not platform:
        platform = (body.platform or "").lower()
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing platform claim (desk|hub|nest)",
        )

    if not rate_limiter.is_allowed(f"refresh:{client_ip}", settings.RATE_LIMIT_LOGIN, 60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many refresh attempts. Please try again later.",
        )

    auth_service = AuthService(db)
    try:
        tokens = auth_service.refresh_access_token(
            body.refresh_token,
            platform=platform,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    return TokenResponse(
        access_token=tokens["access_token"],
        expires_in=tokens["expires_in"],
        refresh_token=tokens["refresh_token"],
        user_id=tokens["user_id"],
        email=tokens["email"],
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """Revoke a refresh token so it can no longer be used to mint new access tokens."""
    AuthService(db).revoke_refresh_token(body.refresh_token)
    return MessageResponse(message="Logged out")


@router.post("/service-token", response_model=ServiceTokenResponse)
async def issue_service_token(
    req: ServiceTokenRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Issue a service token bound to a tenant_id.
    Staff/superuser only - a service token grants machine-to-machine trust
    (e.g. tenant DB credentials), so any regular user self-issuing one for
    their own tenant would be a privilege escalation.
    """
    if not current_user.is_staff and not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    token = create_service_token(req.tenant_id, req.expires_minutes)
    return ServiceTokenResponse(token=token, expires_in=req.expires_minutes * 60)


# Alias with trailing slash
@router.post("/login/", response_model=LoginResponse, include_in_schema=False)
async def login_alias(
    request: Request,
    login_data: LoginRequest,
    db: Session = Depends(get_db),
):
    return await login(request, login_data, db)


# Password reset
@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    request: Request,
    reset_data: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    """Request password reset."""
    client_ip = request.client.host if request.client else "unknown"
    
    # Rate limiting
    if not rate_limiter.is_allowed(f"reset:{client_ip}", settings.RATE_LIMIT_RESET, 3600):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset attempts. Please try again later.",
        )
    
    auth_service = AuthService(db)
    user = auth_service.get_user_by_email(reset_data.email)
    
    # Always return success to prevent email enumeration
    if user:
        await auth_service.send_password_reset_email(user)
    
    return MessageResponse(message="Password reset email sent")


@router.post("/reset-password-confirm", response_model=MessageResponse)
async def reset_password_confirm(
    reset_data: PasswordResetConfirm,
    db: Session = Depends(get_db),
):
    """Confirm password reset."""
    auth_service = AuthService(db)
    user = auth_service.verify_reset_token(reset_data.token)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )
    
    auth_service.update_password(user, reset_data.new_password)
    
    return MessageResponse(message="Password has been reset successfully")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    change_data: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change user password."""
    from app.security import verify_password
    
    if not verify_password(change_data.old_password, current_user.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect password",
        )
    
    auth_service = AuthService(db)
    auth_service.update_password(current_user, change_data.new_password)
    
    return MessageResponse(message="Password changed successfully")


from app.redis_cache import cached

# User info
@router.get("/me", response_model=UserResponse)
@cached(ttl=600, prefix="auth_me", canonical_path="/auth/me")
async def get_current_user_info(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Get current user information."""
    return UserResponse.model_validate(current_user.model_dump())


@router.get("/check-admin", response_model=AdminCheckResponse)
@cached(ttl=1800, prefix="auth_check_admin", canonical_path="/auth/check-admin")
async def check_admin_status(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check if current user has admin privileges."""
    auth_service = AuthService(db)
    return auth_service.check_admin_status(current_user)


# Token validation (for other services)
class TokenValidateRequest(BaseModel):
    token: str

@router.post("/validate-token")
async def validate_token(
    request: Request,
    body: TokenValidateRequest,
    db: Session = Depends(get_db),
):
    """Validate a token and return user info (for inter-service communication)."""
    token = body.token

    try:
        payload = decode_token(token)
        user_id = payload.get("sub")

        if not user_id:
            return {"valid": False, "error": "Invalid token"}

        user = db.get(User, user_id)
        if not user or not user.is_active:
            return {"valid": False, "error": "User not found or inactive"}

        response_data = {
            "valid": True,
            "user_id": str(user.id),
            "tenant_id": str(user.tenant_id),
            "email": user.email,
            "role_id": user.role_id,
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        }

        return response_data
    except Exception as e:
        logger.warning(f"Token validation failed: {e}")
        return {"valid": False, "error": "Invalid or expired token"}

