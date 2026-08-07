"""Decode and verify an access token. Raises AppError(401) on failure."""
import jwt
from dataclasses import dataclass
from typing import Literal

from shared.utils.exceptions import AppError

from app.services.auth_tokens import decode_access_token


@dataclass(frozen=True)
class ValidateResult:
    valid: Literal[True]
    expires_at: int
    claims: dict


def validate_access_token(*, token: str, secret: str) -> ValidateResult:
    try:
        claims = decode_access_token(token, secret=secret)
    except jwt.InvalidTokenError as exc:
        raise AppError(401, "invalid token") from exc
    return ValidateResult(valid=True, expires_at=int(claims["exp"]), claims=claims)


__all__ = ["ValidateResult", "validate_access_token"]
