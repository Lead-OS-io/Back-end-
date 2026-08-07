"""validate service: decode + verify access JWT, raise AppError(401) on failure."""
import time
import uuid

import jwt
import pytest

from app.services.auth_tokens import mint_access_token
from app.services.validate import validate_access_token
from shared.utils.exceptions import AppError


SECRET = "x" * 32


def test_validate_returns_claims_and_expiry():
    user_id = uuid.uuid4()
    token, exp = mint_access_token(
        user_id=user_id, tenant_id=None, status="active",
        ttl_minutes=10, secret=SECRET,
    )
    result = validate_access_token(token=token, secret=SECRET)
    assert result.valid is True
    assert result.expires_at == exp
    assert result.claims["sub"] == str(user_id)


def test_validate_expired_token_raises_401():
    user_id = uuid.uuid4()
    token, _ = mint_access_token(
        user_id=user_id, tenant_id=None, status="active",
        ttl_minutes=-1, secret=SECRET,
    )
    with pytest.raises(AppError) as exc:
        validate_access_token(token=token, secret=SECRET)
    assert exc.value.status_code == 401


def test_validate_bad_signature_raises_401():
    user_id = uuid.uuid4()
    token, _ = mint_access_token(
        user_id=user_id, tenant_id=None, status="active",
        ttl_minutes=10, secret=SECRET,
    )
    with pytest.raises(AppError):
        validate_access_token(token=token, secret="y" * 32)
