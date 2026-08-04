from dataclasses import dataclass

from fastapi import Request

from shared.utils.exceptions import AppError, ForbiddenError


@dataclass(frozen=True)
class Identity:
    user_id: int
    tenant_id: int
    role_id: int | None
    is_superuser: bool


def get_current_identity(request: Request) -> Identity:
    headers = request.headers
    try:
        role_id_raw = headers.get("x-role-id")
        return Identity(
            user_id=int(headers["x-user-id"]),
            tenant_id=int(headers["x-tenant-id"]),
            role_id=int(role_id_raw) if role_id_raw else None,
            is_superuser=headers.get("x-is-superuser", "").lower() == "true",
        )
    except (KeyError, ValueError):
        raise AppError(401, "missing or malformed identity headers")


def require_admin(identity: Identity) -> Identity:
    if not identity.is_superuser and identity.role_id != 1:
        raise ForbiddenError("admin required")
    return identity
