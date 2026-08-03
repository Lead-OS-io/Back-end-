"""
API routes for users service
"""
from typing import Optional, Generator
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlmodel import Session
from sqlalchemy import func, or_, text
import jwt
import math

from app.database import engine
from app.config import settings
from app.services import UserService, AgentSettingService, UserRequestService
from app.models import UserRequest, User
from app.schemas import (
    UserCreate, UserUpdate, UserResponse, UserListResponse,
    AgentSettingCreate, AgentSettingUpdate, AgentSettingResponse,
    UserRequestCreate, UserRequestUpdate, UserRequestResponse, UserRequestListResponse,
)
from app.webhooks import router as webhook_router
from app.google_calendar_routes import router as google_calendar_router
from app.calendar_routes import router as calendar_router
from app.redis_cache import cached
from fastapi import Request

router = APIRouter()
router.include_router(webhook_router)
router.include_router(google_calendar_router)
router.include_router(calendar_router)


def _invalidate_shared_cache_safe(*, user_id: Optional[str]) -> None:
    """Same pattern as cases-service: clear this user's cached responses so
    an update/delete is visible immediately instead of waiting out the TTL."""
    try:
        from app.redis_client import redis_client
        if not redis_client:
            return
        import asyncio

        patterns = ["ariadesk:shared:u:global:*"]
        uid = (str(user_id).strip() if user_id else "")
        if uid:
            patterns.append(f"ariadesk:shared:u:{uid}:*")

        async def _do():
            for pattern in patterns:
                batch = []
                async for k in redis_client.scan_iter(match=pattern, count=500):
                    batch.append(k)
                    if len(batch) >= 500:
                        await redis_client.delete(*batch)
                        batch = []
                if batch:
                    await redis_client.delete(*batch)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_do())
        else:
            loop.create_task(_do())
    except Exception:
        return


def verify_token(authorization: str = Header(...)) -> dict:
    """Verify JWT signature and return the payload."""
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")


def get_tenant_id(
    x_tenant_id: str = Header(...),
    token: dict = Depends(verify_token),
) -> UUID:
    """Resolve tenant from the X-Tenant-ID header and enforce that it matches
    the tenant_id claim in the (signature-verified) JWT. Blocks cross-tenant access."""
    try:
        header_tenant = UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID header")

    token_tenant = token.get("tenant_id")
    if not token_tenant:
        raise HTTPException(status_code=401, detail="Token missing tenant_id")
    if str(header_tenant) != str(token_tenant):
        raise HTTPException(status_code=403, detail="X-Tenant-ID does not match token tenant_id")
    return header_tenant


def _is_admin_token(token: dict) -> bool:
    """Same super-admin convention used elsewhere in this service:
    is_superuser claim, or role_id == 1."""
    role_id = token.get("role_id")
    try:
        role_id = int(role_id) if role_id is not None else None
    except Exception:
        role_id = None
    return bool(token.get("is_superuser")) or role_id == 1


def _require_self_or_admin(token: dict, target_user_id: UUID) -> None:
    """Only an admin may read/modify another tenant member's record - a
    regular user may only act on their own."""
    if _is_admin_token(token):
        return
    caller_id = token.get("sub") or token.get("user_id")
    if not caller_id or str(caller_id) != str(target_user_id):
        raise HTTPException(status_code=403, detail="Forbidden")


def get_tenant_db(tenant_id: UUID = Depends(get_tenant_id)) -> Generator[Session, None, None]:
    """Same session as get_db, but scoped to the validated tenant for RLS:
    sets the app.tenant_id GUC read by the policies in db/rls_policies.sql.
    Harmless no-op until that SQL is applied (see db/README.md)."""
    with Session(engine) as session:
        session.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": str(tenant_id)})
        yield session


# =============================================================================
# USER CRUD ENDPOINTS
# =============================================================================

@router.post("/api/users", response_model=UserResponse, status_code=201)
def create_user(
    user_data: UserCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Create a new user"""
    if str(user_data.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=400, detail="Tenant ID mismatch")

    existing_user = UserService.get_user_by_email(db, user_data.email, tenant_id)
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    return UserService.create_user(db, user_data, is_admin=_is_admin_token(token))


@router.get("/api/users/stats")
@cached(ttl=600, prefix="user_stats")
def get_user_stats(
    request: Request,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_tenant_db)
):
    """Get aggregated user statistics (total, active, agents, opt-in count)."""
    total_users = db.query(func.count(User.id)).filter(User.tenant_id == tenant_id).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(
        User.tenant_id == tenant_id,
        User.is_active == True
    ).scalar() or 0
    agents = db.query(func.count(User.id)).filter(
        User.tenant_id == tenant_id,
        User.is_superuser == False,
        or_(User.role_id != 1, User.role_id.is_(None))
    ).scalar() or 0
    opt_in_users = db.query(func.count(User.id)).filter(
        User.tenant_id == tenant_id,
        User.accepted_campaign_terms_at.isnot(None)
    ).scalar() or 0
    return {
        "total_users": total_users,
        "active_users": active_users,
        "agents": agents,
        "opt_in_records": opt_in_users
    }


@router.get("/api/users/{user_id}", response_model=UserResponse)
@cached(ttl=600, prefix="user_detail")
def get_user(
    request: Request,
    user_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Get user by ID"""
    _require_self_or_admin(token, user_id)
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/api/users", response_model=UserListResponse)
@cached(ttl=300, prefix="user_list")
def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    is_superuser: Optional[str] = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_tenant_db)
):
    """List users with pagination and filtering"""
    skip = (page - 1) * size

    is_superuser_bool = None
    if is_superuser is not None:
        if is_superuser.lower() in ('true', 'super_admin'):
            is_superuser_bool = True
        elif is_superuser.lower() in ('false', 'agent'):
            is_superuser_bool = False

    users, total = UserService.list_users(
        db, tenant_id, skip, size, search, is_active, is_superuser_bool
    )

    return UserListResponse(
        items=users,
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total > 0 else 0
    )


@router.put("/api/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Update user."""
    _require_self_or_admin(token, user_id)
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    updated_user = UserService.update_user(db, user, user_data, is_admin=_is_admin_token(token))
    db.refresh(updated_user)
    _invalidate_shared_cache_safe(user_id=str(user_id))
    return updated_user


@router.delete("/api/users/{user_id}", status_code=204)
def delete_user(
    user_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Delete user (soft delete)"""
    _require_self_or_admin(token, user_id)
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    UserService.delete_user(db, user)
    _invalidate_shared_cache_safe(user_id=str(user_id))
    return None


# =============================================================================
# AGENT SETTINGS ENDPOINTS (NEST)
# =============================================================================

@router.get("/api/users/{user_id}/agent-settings", response_model=AgentSettingResponse)
@cached(ttl=600, prefix="agent_settings")
def get_agent_settings(
    request: Request,
    user_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_tenant_db)
):
    """Get agent settings for user"""
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return AgentSettingService.get_or_create(db, user_id, tenant_id)


@router.put("/api/users/{user_id}/agent-settings", response_model=AgentSettingResponse)
def update_agent_settings(
    user_id: UUID,
    settings_data: AgentSettingUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_tenant_db)
):
    """Update agent settings"""
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    settings_obj = AgentSettingService.get_or_create(db, user_id, tenant_id)
    return AgentSettingService.update_settings(db, settings_obj, settings_data.settings)


# =============================================================================
# USER REQUESTS ENDPOINTS (NEST)
# =============================================================================

@router.post("/api/users/{user_id}/requests", response_model=UserRequestResponse, status_code=201)
def create_user_request(
    user_id: UUID,
    request_data: UserRequestCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Create a new user request"""
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    created_by_id = UUID(token.get("user_id", str(user_id)))

    return UserRequestService.create_request(
        db, user_id, tenant_id,
        request_data.request_type,
        request_data.data,
        created_by_id,
        request_data.notes
    )


@router.get("/api/users/{user_id}/requests", response_model=UserRequestListResponse)
@cached(ttl=300, prefix="user_requests")
def list_user_requests(
    request: Request,
    user_id: UUID,
    request_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    db: Session = Depends(get_tenant_db)
):
    """List user requests"""
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    skip = (page - 1) * size
    requests, total = UserRequestService.list_requests(
        db, user_id, tenant_id, request_type, status, skip, size
    )

    return UserRequestListResponse(
        items=requests,
        total=total,
        page=page,
        size=size
    )


@router.put("/api/users/{user_id}/requests/{request_id}", response_model=UserRequestResponse)
def update_user_request(
    user_id: UUID,
    request_id: UUID,
    request_data: UserRequestUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    token: dict = Depends(verify_token),
    db: Session = Depends(get_tenant_db)
):
    """Update a user request"""
    user = UserService.get_user(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    request = db.query(UserRequest).filter_by(
        id=request_id, user_id=user_id, tenant_id=tenant_id
    ).first()

    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    reviewed_by_id = None
    if request_data.status in ["approved", "rejected"]:
        reviewer_claim = token.get("user_id") or token.get("sub")
        if not reviewer_claim:
            raise HTTPException(status_code=401, detail="Token missing user id")
        reviewed_by_id = UUID(reviewer_claim)

    return UserRequestService.update_request(
        db, request,
        request_data.data,
        request_data.status,
        request_data.notes,
        reviewed_by_id
    )
