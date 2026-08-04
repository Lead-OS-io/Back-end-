import jwt
import pytest

from app.config import Settings
from app.utils.jwt_keys import decode_user_token


def _settings() -> Settings:
    return Settings(
        SERVICE_NAME="api-gateway",
        INTER_SERVICE_SECRET="iss",
        SECRET_KEY="fallback-secret",
        DESK_SECRET_KEY="desk-secret",
        HUB_SECRET_KEY="hub-secret",
        NEST_SECRET_KEY="nest-secret",
    )


def _token(claims: dict, key: str) -> str:
    return jwt.encode({**claims, "exp": 9999999999}, key, algorithm="HS256")


def test_decode_selects_platform_key():
    s = _settings()
    token = _token({"platform": "desk", "sub": "1"}, "desk-secret")
    assert decode_user_token(token, s)["sub"] == "1"
    with pytest.raises(jwt.InvalidTokenError):
        decode_user_token(_token({"platform": "desk"}, "wrong-key"), s)


def test_decode_falls_back_to_secret_key():
    # Sin claves de plataforma configuradas, SECRET_KEY firma todo (comportamiento
    # real de auth-service: _get_platform_key usa "desk" -> DESK_SECRET_KEY or SECRET_KEY).
    s = Settings(
        SERVICE_NAME="api-gateway",
        INTER_SERVICE_SECRET="iss",
        SECRET_KEY="fallback-secret",
    )
    token = _token({"sub": "2"}, "fallback-secret")
    assert decode_user_token(token, s)["sub"] == "2"


def test_decode_rejects_expired():
    s = Settings(
        SERVICE_NAME="api-gateway",
        INTER_SERVICE_SECRET="iss",
        SECRET_KEY="fallback-secret",
    )
    token = jwt.encode({"exp": 1}, "fallback-secret", algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_user_token(token, s)
