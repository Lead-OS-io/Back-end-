"""FastAPI dependencies for tenant DB routing.

Uso esperado en microservicios:

- Inicializar una vez en startup:
    init_tenant_db_router(
        tenant_service_url=...,
        control_plane_secret_key=...,
        access_token_secret_key=...,  # (opcional) si difiere
    )

- En endpoints:
    db = Depends(get_tenant_db_session)

Esto garantiza:
- `X-Tenant-ID` obligatorio
- `X-Tenant-ID` == `tenant_id` del JWT (validando firma localmente)
- DB Session conecta a la DB específica del tenant
"""

from __future__ import annotations

from typing import Generator, Optional

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session

from jose import jwt, JWTError

from .router import TenantDbRouter, TenantDbNotProvisionedError, TenantDbRoutingError


_router: Optional[TenantDbRouter] = None
_access_token_secret_key: Optional[str] = None


def init_tenant_db_router(
    *,
    tenant_service_url: str,
    control_plane_secret_key: str,
    access_token_secret_key: Optional[str] = None,
) -> TenantDbRouter:
    global _router
    global _access_token_secret_key
    _router = TenantDbRouter(
        tenant_service_url=tenant_service_url,
        control_plane_secret_key=control_plane_secret_key,
    )
    _access_token_secret_key = (access_token_secret_key or control_plane_secret_key or "").strip() or None
    return _router


def get_tenant_db_router() -> TenantDbRouter:
    if _router is None:
        raise RuntimeError("TenantDbRouter not initialized. Call init_tenant_db_router() on startup.")
    return _router


def require_tenant_header_matches_token(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("invalid scheme")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    secret = (_access_token_secret_key or "").strip()
    if not secret:
        raise RuntimeError(
            "Access token secret not configured. Pass access_token_secret_key to init_tenant_db_router()."
        )

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Access token required")

    token_tenant_id = payload.get("tenant_id")
    if not token_tenant_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing tenant_id")

    if str(x_tenant_id).strip() != str(token_tenant_id).strip():
        raise HTTPException(status_code=403, detail="X-Tenant-ID does not match token tenant_id")
    return str(x_tenant_id).strip()


def get_tenant_db_session(
    tenant_id: str = Depends(require_tenant_header_matches_token),
) -> Generator[Session, None, None]:
    router = get_tenant_db_router()
    try:
        engine = router.get_engine(tenant_id)
    except TenantDbNotProvisionedError:
        raise HTTPException(status_code=503, detail="Tenant database is not provisioned yet")
    except TenantDbRoutingError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to resolve tenant database")
    with Session(engine) as session:
        yield session

