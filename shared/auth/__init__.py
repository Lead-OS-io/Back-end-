"""
Shared authentication utilities for all microservices.
"""
from shared.auth.jwt import JWTHandler, decode_token, verify_token
from shared.auth.dependencies import (
    get_current_user,
    get_current_tenant,
    require_auth,
    require_permissions,
)

__all__ = [
    "JWTHandler",
    "decode_token",
    "verify_token",
    "get_current_user",
    "get_current_tenant",
    "require_auth",
    "require_permissions",
]

