"""
FastAPI dependencies for authentication and authorization.
These are used by all microservices.
"""
from typing import Optional, List, Callable
from functools import wraps
from fastapi import Depends, HTTPException, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from shared.auth.jwt import decode_token
from shared.schemas.user import UserContext, TokenPayload
from shared.schemas.tenant import TenantContext
from shared.utils.exceptions import AuthenticationError, AuthorizationError

security = HTTPBearer(auto_error=False)


async def get_token_from_header(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_service_key: Optional[str] = Header(None),
) -> Optional[str]:
    """Extract token from Authorization header."""
    if credentials:
        return credentials.credentials
    return None


async def get_tenant_id_from_header(
    request: Request,
    x_tenant_id: Optional[str] = Header(None),
) -> Optional[str]:
    """Extract tenant ID from header or request state."""
    # First check header
    if x_tenant_id:
        return x_tenant_id
    
    # Then check request state (set by middleware)
    if hasattr(request.state, "tenant_id"):
        return request.state.tenant_id
    
    return None


async def get_current_user(
    token: Optional[str] = Depends(get_token_from_header),
) -> Optional[UserContext]:
    """
    Get the current authenticated user from the JWT token.
    Returns None if no valid token is provided.
    """
    if not token:
        return None
    
    try:
        payload = decode_token(token)
        return UserContext(
            id=payload.sub,
            tenant_id=payload.tenant_id,
            email=payload.email,
            role_id=payload.role_id,
            is_staff=payload.is_staff,
            is_superuser=payload.is_superuser,
        )
    except AuthenticationError:
        return None


async def get_current_tenant(
    request: Request,
    tenant_id: Optional[str] = Depends(get_tenant_id_from_header),
    user: Optional[UserContext] = Depends(get_current_user),
) -> Optional[TenantContext]:
    """
    Get the current tenant context.
    Resolved from header, token, or request state.
    """
    # Get tenant_id from user token if not in header
    resolved_tenant_id = tenant_id or (user.tenant_id if user else None)
    
    if not resolved_tenant_id:
        return None
    
    # Return minimal context - full tenant data should be fetched from tenant service
    return TenantContext(
        id=resolved_tenant_id,
        slug="",  # Will be populated by tenant service if needed
    )


def require_auth(
    user: Optional[UserContext] = Depends(get_current_user),
) -> UserContext:
    """Require authentication - raises 401 if not authenticated."""
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_tenant(
    tenant: Optional[TenantContext] = Depends(get_current_tenant),
) -> TenantContext:
    """Require tenant context - raises 400 if no tenant."""
    if not tenant:
        raise HTTPException(
            status_code=400,
            detail="Tenant context required",
        )
    return tenant


def require_permissions(required_permissions: List[str]):
    """
    Dependency factory that requires specific permissions.
    
    Usage:
        @router.get("/admin")
        async def admin_endpoint(
            user: UserContext = Depends(require_permissions(["admin:read"]))
        ):
            ...
    """
    async def check_permissions(
        user: UserContext = Depends(require_auth),
    ) -> UserContext:
        # Superusers have all permissions
        if user.is_superuser:
            return user
        
        # Check if user has all required permissions
        user_permissions = set(user.permissions)
        required = set(required_permissions)
        
        if not required.issubset(user_permissions):
            missing = required - user_permissions
            raise HTTPException(
                status_code=403,
                detail=f"Missing permissions: {', '.join(missing)}",
            )
        
        return user
    
    return check_permissions


def require_staff(
    user: UserContext = Depends(require_auth),
) -> UserContext:
    """Require staff user."""
    if not user.is_staff and not user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Staff access required",
        )
    return user


def require_superuser(
    user: UserContext = Depends(require_auth),
) -> UserContext:
    """Require superuser."""
    if not user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Superuser access required",
        )
    return user

