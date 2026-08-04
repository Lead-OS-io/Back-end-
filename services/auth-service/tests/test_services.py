"""Tests de lógica pura: security (hash/verify, tokens multi-plataforma, Fernet)."""
import pytest

from app.services import security
from app.serializers.user import user_to_response
from app.models import User
import uuid
from datetime import datetime


def test_password_hash_roundtrip():
    hashed = security.get_password_hash("Secret123")
    assert security.verify_password("Secret123", hashed)
    assert not security.verify_password("wrong", hashed)


def test_access_token_roundtrip():
    token = security.create_access_token(
        user_id="1", tenant_id="1", email="u@x.com")
    claims = security.decode_token(token)
    assert claims["sub"] == "1"
    assert claims["type"] == "access"
    assert "platform" not in claims


def test_decode_token_rejects_wrong_key(monkeypatch):
    token = security.create_access_token(
        user_id="1", tenant_id="1", email="u@x.com")
    monkeypatch.setattr("app.services.security.settings.SECRET_KEY", "other-key", raising=False)
    import pytest
    with pytest.raises(ValueError):
        security.decode_token(token)


def test_encryption_fernet_roundtrip():
    payload = "sensitive-data"
    enc = security.Encryption.encrypt(payload)
    assert enc != payload
    assert security.Encryption.decrypt(enc) == payload


def test_refresh_token_has_type_refresh():
    token = security.create_refresh_token(user_id="1", tenant_id="1")
    claims = security.decode_token(token)
    assert claims["type"] == "refresh"


def test_hash_token_is_stable():
    assert security.hash_token("abc") == security.hash_token("abc")
    assert security.hash_token("abc") != security.hash_token("abd")


def test_user_to_response_serializes_model():
    user = User(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x.com",
        first_name="U", last_name="N", is_active=True, is_staff=False,
        is_superuser=False, role_id=None, date_joined=datetime.utcnow(),
        last_login=None, first_login=True,
    )
    resp = user_to_response(user)
    assert resp.email == "u@x.com"
    assert resp.first_login is True
