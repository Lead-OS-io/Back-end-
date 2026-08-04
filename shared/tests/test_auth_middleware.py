from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from shared.auth.dependencies import Identity, get_current_identity
from shared.auth.middleware import ServiceTokenMiddleware
from shared.auth.service_token import mint_service_token
from shared.utils.exceptions import register_exception_handlers

SECRET = "test-inter-service-secret"


def _make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=SECRET)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/me")
    def me(identity: Identity = Depends(get_current_identity)):
        return {"user_id": identity.user_id, "tenant_id": identity.tenant_id,
                "role_id": identity.role_id, "is_superuser": identity.is_superuser}

    return app


def test_health_is_exempt():
    assert TestClient(_make_app()).get("/health").status_code == 200


def test_request_without_service_token_is_401():
    assert TestClient(_make_app()).get("/me").status_code == 401


def test_request_with_invalid_service_token_is_401():
    resp = TestClient(_make_app()).get("/me", headers={"X-Service-Token": "garbage"})
    assert resp.status_code == 401


def test_valid_service_token_passes_and_identity_is_parsed():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    resp = TestClient(_make_app()).get("/me", headers={
        "X-Service-Token": token,
        "X-User-Id": "7",
        "X-Tenant-Id": "42",
        "X-Role-Id": "1",
        "X-Is-Superuser": "true",
    })
    assert resp.status_code == 200
    assert resp.json() == {"user_id": 7, "tenant_id": 42, "role_id": 1, "is_superuser": True}


def test_valid_token_but_missing_identity_headers_is_401():
    token = mint_service_token(secret=SECRET, issuer="api-gateway")
    resp = TestClient(_make_app()).get("/me", headers={"X-Service-Token": token})
    assert resp.status_code == 401
