"""PublicAuthMiddleware: validates X-User-Id on /public/* paths.

Used by the public router in files-service. The api-gateway decodes the user
JWT and injects X-User-Id, X-Tenant-Id, X-Is-Superuser headers before
forwarding. This middleware enforces that those headers exist and are well
formed on any /public/* request, and exposes the resulting Identity via a
FastAPI dependency.

Not used by /internal/* routes (those are protected by ServiceTokenMiddleware
at the app level).
"""
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from shared.utils.exceptions import AppError


PUBLIC_PATH_PREFIX = "/public"


@dataclass(frozen=True)
class Identity:
    user_id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    is_superuser: bool


def _parse_uuid(raw: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        raise AppError(401, f"invalid {field}")


class PublicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(PUBLIC_PATH_PREFIX):
            return await call_next(request)

        try:
            user_id_raw = request.headers.get("X-User-Id")
            if not user_id_raw:
                return JSONResponse({"detail": "missing X-User-Id"}, status_code=401)
            user_id = _parse_uuid(user_id_raw, "X-User-Id")

            tenant_id_raw = request.headers.get("X-Tenant-Id")
            tenant_id = _parse_uuid(tenant_id_raw, "X-Tenant-Id") if tenant_id_raw else None

            is_superuser = request.headers.get("X-Is-Superuser", "").lower() == "true"

            request.state.identity = Identity(
                user_id=user_id,
                tenant_id=tenant_id,
                is_superuser=is_superuser,
            )
            return await call_next(request)
        except AppError as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def get_current_identity(request: Request) -> Identity:
    identity = getattr(request.state, "identity", None)
    if identity is None:
        raise AppError(401, "identity not resolved")
    return identity


__all__ = ["Identity", "PublicAuthMiddleware", "get_current_identity"]
