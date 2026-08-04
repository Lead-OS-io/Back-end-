"""Contrato del router de auth-service (Task 18, fuente de verdad del comportamiento).

Cubre todos los endpoints del inventario viejo + el endpoint NUEVO /register
(publica user.registered). Los nombres `app.services.auth.*` y
`app.services.google_oauth.*` son el contrato que Task 20 implementa.
"""
import uuid
from datetime import datetime
from unittest.mock import MagicMock

from shared.utils.exceptions import AppError

TOKENS = {"access_token": "a", "expires_in": 3600, "refresh_token": "r",
          "user_id": "1", "email": "u@x.com"}
FULL_LOGIN = {**TOKENS, "user": {
    "id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4()), "email": "u@x.com",
    "first_name": "U", "last_name": None, "is_active": True, "is_staff": False,
    "is_superuser": False, "role_id": None, "date_joined": datetime.utcnow().isoformat(),
    "last_login": None, "first_login": False,
}}


class _StubUser:
    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.email = "u@x.com"
        self.first_name = "U"
        self.last_name = None
        self.is_active = True
        self.is_staff = False
        self.is_superuser = False
        self.role_id = None
        self.date_joined = datetime.utcnow()
        self.last_login = None
        self.first_login = False
        for k, v in kw.items():
            setattr(self, k, v)


# ---- Health ----
def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "auth-service"


# ---- Token (OAuth2 form) ----
def test_token_returns_tokens(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.login_user",
                        lambda **kwargs: dict(TOKENS))
    resp = client.post("/api/auth/token",
                       data={"username": "u@x.com", "password": "pw", "platform": "desk"},
                       headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "a"


# ---- Login (JSON) ----
def test_login_returns_tokens(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.login_user",
                        lambda **kwargs: dict(FULL_LOGIN))
    resp = client.post("/api/auth/login",
                       json={"email": "u@x.com", "password": "pw", "platform": "desk"},
                       headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "u@x.com"


def test_login_wrong_credentials_is_401(client, svc_headers, monkeypatch):
    def boom(**kwargs):
        raise AppError(401, "invalid credentials")

    monkeypatch.setattr("app.services.auth.login_user", boom)
    resp = client.post("/api/auth/login",
                       json={"email": "u@x.com", "password": "bad", "platform": "desk"},
                       headers=svc_headers)
    assert resp.status_code == 401


# ---- Register (NUEVO) ----
def test_register_returns_user(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.register_user",
                        lambda **kwargs: _StubUser())
    resp = client.post("/api/auth/register",
                       json={"email": "u@x.com", "password": "Pw123456", "full_name": "U"},
                       headers=svc_headers)
    assert resp.status_code == 201
    assert resp.json()["email"] == "u@x.com"


def test_register_short_password_is_422(client, svc_headers):
    resp = client.post("/api/auth/register",
                       json={"email": "u@x.com", "password": "short", "full_name": "U"},
                       headers=svc_headers)
    assert resp.status_code == 422


# ---- Refresh ----
def test_refresh_requires_body(client, svc_headers):
    resp = client.post("/api/auth/refresh", json={}, headers=svc_headers)
    assert resp.status_code == 422


def test_refresh_returns_tokens(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.refresh_user_tokens",
                        lambda **kwargs: dict(TOKENS))
    resp = client.post("/api/auth/refresh",
                       json={"refresh_token": "tok", "platform": "desk"},
                       headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] == "r"


# ---- Logout ----
def test_logout_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.revoke_refresh_token",
                        lambda **kwargs: None)
    resp = client.post("/api/auth/logout", json={"refresh_token": "tok"},
                       headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "Logged out"


# ---- Service token (staff/superuser) ----
def test_service_token_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.issue_service_token",
                        lambda **kwargs: {"token": "st", "expires_in": 86400})
    resp = client.post("/api/auth/service-token",
                       json={"tenant_id": "t1", "expires_minutes": 60},
                       headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["token"] == "st"


def test_service_token_forbidden_for_regular_user(client, svc_headers, monkeypatch):
    from app.config import Settings
    from shared.auth.dependencies import Identity, get_current_identity

    app = client.app
    app.dependency_overrides[get_current_identity] = (
        lambda: Identity(user_id=2, tenant_id=1, role_id=2, is_superuser=False))

    def boom(**kwargs):
        raise AppError(403, "Forbidden")

    monkeypatch.setattr("app.services.auth.issue_service_token", boom)
    resp = client.post("/api/auth/service-token",
                       json={"tenant_id": "t1", "expires_minutes": 60},
                       headers=svc_headers)
    assert resp.status_code == 403


# ---- Password reset ----
def test_reset_password_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.reset_password_request",
                        lambda **kwargs: {"message": "Password reset email sent"})
    resp = client.post("/api/auth/reset-password",
                       json={"email": "u@x.com"}, headers=svc_headers)
    assert resp.status_code == 200


def test_reset_password_confirm_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.reset_password_confirm",
                        lambda **kwargs: {"message": "Password has been reset successfully"})
    resp = client.post("/api/auth/reset-password-confirm",
                       json={"token": "t", "new_password": "NewPass123"},
                       headers=svc_headers)
    assert resp.status_code == 200


def test_change_password_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.change_user_password",
                        lambda **kwargs: {"message": "Password changed successfully"})
    resp = client.post("/api/auth/change-password",
                       json={"old_password": "old", "new_password": "NewPass123"},
                       headers=svc_headers)
    assert resp.status_code == 200


# ---- Me / check-admin ----
def test_me_returns_user(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.get_current_user_info",
                        lambda **kwargs: _StubUser())
    resp = client.get("/api/auth/me", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "u@x.com"


def test_check_admin_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.check_admin_status",
                        lambda **kwargs: {"isAdmin": True, "permissions": []})
    resp = client.get("/api/auth/check-admin", headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["isAdmin"] is True


# ---- Validate token (inter-service) ----
def test_validate_token_ok(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.auth.validate_user_token",
                        lambda **kwargs: {"valid": True, "user_id": "1"})
    resp = client.post("/api/auth/validate-token", json={"token": "tok"},
                       headers=svc_headers)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


# ---- Google OAuth ----
def test_google_check_config(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.google_oauth.check_config",
                        lambda **kwargs: {"configured": True})
    resp = client.get("/api/auth/google/check-config", headers=svc_headers)
    assert resp.status_code == 200


def test_google_status(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.google_oauth.get_status",
                        lambda **kwargs: {"connected": False})
    resp = client.get("/api/auth/google/status", headers=svc_headers)
    assert resp.status_code == 200


def test_google_auth_url(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.google_oauth.get_auth_url",
                        lambda **kwargs: {"auth_url": "https://accounts.google.com/o/oauth2/auth"})
    resp = client.get("/api/auth/google/auth-url", headers=svc_headers)
    assert resp.status_code == 200


def test_google_callback(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.google_oauth.handle_callback",
                        lambda **kwargs: {"status": "ok"})
    resp = client.get("/api/auth/google/callback?code=abc", headers=svc_headers)
    assert resp.status_code == 200


def test_google_disconnect(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.google_oauth.disconnect",
                        lambda **kwargs: {"message": "disconnected"})
    resp = client.post("/api/auth/google/disconnect", headers=svc_headers)
    assert resp.status_code == 200


def test_google_access_token(client, svc_headers, monkeypatch):
    monkeypatch.setattr("app.services.google_oauth.get_access_token",
                        lambda **kwargs: {"access_token": "gat"})
    resp = client.get("/api/auth/google/access-token", headers=svc_headers)
    assert resp.status_code == 200


# ---- Enforcement ----
def test_missing_service_token_is_401(client):
    assert client.post("/api/auth/login",
                       json={"email": "a@b.c", "password": "x"}).status_code == 401


def test_private_route_requires_identity_headers(client, svc_headers, monkeypatch):
    app = client.app
    from shared.auth.dependencies import get_current_identity

    def no_identity():
        raise AppError(401, "missing or malformed identity headers")

    app.dependency_overrides[get_current_identity] = no_identity
    resp = client.get("/api/auth/me", headers=svc_headers)
    assert resp.status_code == 401
