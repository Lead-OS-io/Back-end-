import hashlib
import time
import uuid

import jwt
import pytest

from app.services.auth_tokens import (
    decode_access_token,
    hash_refresh,
    mint_access_token,
    mint_refresh_token,
)


SECRET = "x" * 32


def test_mint_access_token_returns_string_and_expires():
    user_id = uuid.uuid4()
    token, exp = mint_access_token(
        user_id=user_id, tenant_id=None, status="active",
        ttl_minutes=15, secret=SECRET,
    )
    assert isinstance(token, str)
    assert exp > int(time.time())


def test_decode_access_token_round_trip():
    user_id = uuid.uuid4()
    token, _ = mint_access_token(
        user_id=user_id, tenant_id=uuid.uuid4(), status="active",
        ttl_minutes=10, secret=SECRET,
    )
    claims = decode_access_token(token, secret=SECRET)
    assert claims["sub"] == str(user_id)
    assert claims["status"] == "active"


def test_decode_access_token_rejects_bad_signature():
    token, _ = mint_access_token(
        user_id=uuid.uuid4(), tenant_id=None, status="active",
        ttl_minutes=10, secret=SECRET,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, secret="y" * 32)


def test_mint_refresh_token_is_unique_and_urlsafe():
    a = mint_refresh_token()
    b = mint_refresh_token()
    assert a != b
    assert " " not in a and "\n" not in a


def test_hash_refresh_is_sha256_of_input():
    raw = mint_refresh_token()
    digest = hash_refresh(raw)
    assert digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert len(digest) == 64


def test_hash_refresh_is_deterministic():
    raw = "same-token-value"
    assert hash_refresh(raw) == hash_refresh(raw)
