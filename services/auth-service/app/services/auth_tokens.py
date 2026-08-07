"""Token minting and verification for auth-service."""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from typing import Optional, Tuple

import jwt


def mint_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: Optional[uuid.UUID],
    status: str,
    ttl_minutes: int,
    secret: str,
    algorithm: str = "HS256",
) -> Tuple[str, int]:
    now = int(time.time())
    expires_at = now + ttl_minutes * 60
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id) if tenant_id else None,
        "status": status,
        "iat": now,
        "exp": expires_at,
        "type": "user",
    }
    return jwt.encode(payload, secret, algorithm=algorithm), expires_at


def decode_access_token(
    token: str,
    *,
    secret: str,
    algorithm: str = "HS256",
) -> dict:
    claims = jwt.decode(token, secret, algorithms=[algorithm])
    if claims.get("type") != "user":
        raise jwt.InvalidTokenError("not a user token")
    return claims


def mint_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "mint_access_token",
    "decode_access_token",
    "mint_refresh_token",
    "hash_refresh",
]
