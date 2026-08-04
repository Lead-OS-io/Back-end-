import time

import jwt
import pytest

from shared.auth.service_token import decode_service_token, mint_service_token

SECRET = "test-inter-service-secret"


def test_mint_and_decode_roundtrip():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    claims = decode_service_token(token, secret=SECRET)
    assert claims["iss"] == "api-gateway"
    assert claims["type"] == "service"
    assert 0 < claims["exp"] - claims["iat"] <= 60


def test_decode_rejects_wrong_secret():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    with pytest.raises(jwt.InvalidTokenError):
        decode_service_token(token, secret="other-secret")


def test_decode_rejects_expired():
    token = mint_service_token(secret=SECRET, issuer="api-gateway", ttl_seconds=-1)
    time.sleep(0.01)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_service_token(token, secret=SECRET)


def test_decode_rejects_non_service_type():
    token = jwt.encode({"type": "user", "exp": 9999999999}, SECRET, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_service_token(token, secret=SECRET)
