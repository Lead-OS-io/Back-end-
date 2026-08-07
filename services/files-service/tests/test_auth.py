"""PublicAuthMiddleware decodes X-User-Id and rejects malformed values."""
import uuid

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.auth import Identity, PublicAuthMiddleware, get_current_identity
from shared.utils.exceptions import register_exception_handlers


def _make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(PublicAuthMiddleware)

    @app.get("/public/ping")
    def ping(identity: Identity = Depends(get_current_identity)):
        return {
            "user_id": str(identity.user_id),
            "tenant_id": str(identity.tenant_id) if identity.tenant_id else None,
            "is_superuser": identity.is_superuser,
        }

    @app.get("/internal/ping")
    def internal_ping():
        return {"ok": True}

    return app


def test_public_path_without_user_id_is_401():
    resp = TestClient(_make_app()).get("/public/ping")
    assert resp.status_code == 401


def test_public_path_with_invalid_uuid_is_401():
    resp = TestClient(_make_app()).get("/public/ping", headers={"X-User-Id": "not-a-uuid"})
    assert resp.status_code == 401


def test_public_path_with_valid_user_id_returns_identity():
    uid = str(uuid.uuid4())
    resp = TestClient(_make_app()).get(
        "/public/ping",
        headers={"X-User-Id": uid, "X-Tenant-Id": uid, "X-Is-Superuser": "false"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == uid
    assert body["tenant_id"] == uid
    assert body["is_superuser"] is False


def test_non_public_path_is_unaffected():
    resp = TestClient(_make_app()).get("/internal/ping")
    assert resp.status_code == 200


def test_is_superuser_true_parses_correctly():
    uid = str(uuid.uuid4())
    resp = TestClient(_make_app()).get(
        "/public/ping",
        headers={"X-User-Id": uid, "X-Is-Superuser": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_superuser"] is True
