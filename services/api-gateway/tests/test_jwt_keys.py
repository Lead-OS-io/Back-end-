import jwt
import pytest

from app.config import Settings
from app.utils.jwt_keys import decode_user_token


def _settings() -> Settings:
    return Settings(
        SERVICE_NAME="api-gateway",
        INTER_SERVICE_SECRET="iss",
        SECRET_KEY="user-secret",
    )


def _token(claims: dict, key: str) -> str:
    return jwt.encode({**claims, "exp": 9999999999}, key, algorithm="HS256")


def test_decode_with_secret_key():
    s = _settings()
    token = _token({"sub": "1"}, "user-secret")
    assert decode_user_token(token, s)["sub"] == "1"
    with pytest.raises(jwt.InvalidTokenError):
        decode_user_token(_token({"sub": "1"}, "wrong-key"), s)


def test_decode_rejects_expired():
    s = _settings()
    token = jwt.encode({"exp": 1}, "user-secret", algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_user_token(token, s)
