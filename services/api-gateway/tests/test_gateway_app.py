import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from shared.auth.service_token import decode_service_token

SECRET = "user-secret"
ISS = "test-inter-service-secret"


def _settings() -> Settings:
    return Settings(
        SERVICE_NAME="api-gateway", INTER_SERVICE_SECRET=ISS, SECRET_KEY=SECRET,
        REDIS_URL="redis://fake:6379/0", RATE_LIMIT_PER_MINUTE=3,
    )


def _upstream(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "path": request.url.path,
        "service_token": request.headers.get("x-service-token"),
        "user_id": request.headers.get("x-user-id"),
        "tenant_id": request.headers.get("x-tenant-id"),
    })


@pytest.fixture
def client():
    import fakeredis
    import fakeredis.aioredis
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(_upstream))
    app = create_app(_settings(), http_client=http_client,
                     redis_client=fakeredis.aioredis.FakeRedis(
                         decode_responses=True, server=fakeredis.FakeServer()))
    with TestClient(app) as c:
        yield c


def _user_token() -> str:
    # Claims reales de auth-service: `sub` es el user id.
    return jwt.encode({"sub": "7", "tenant_id": "42", "exp": 9999999999},
                      SECRET, algorithm="HS256")


def test_health_is_public_and_has_security_headers(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_private_route_without_jwt_is_401(client):
    assert client.get("/api/users/me").status_code == 401


def test_client_cannot_forge_identity_headers(client):
    resp = client.get("/api/users/me", headers={
        "Authorization": f"Bearer {_user_token()}",
        "X-User-Id": "999", "X-Tenant-Id": "999",
    })
    body = resp.json()
    assert resp.status_code == 200
    assert body["user_id"] == "7" and body["tenant_id"] == "42"


def test_gateway_injects_service_token_and_identity(client):
    resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {_user_token()}"})
    body = resp.json()
    claims = decode_service_token(body["service_token"], secret=ISS)
    assert claims["iss"] == "api-gateway"
    assert body["user_id"] == "7"


def test_public_auth_route_proxied_with_service_token_but_no_identity(client):
    resp = client.post("/api/auth/login")
    body = resp.json()
    assert resp.status_code == 200
    decode_service_token(body["service_token"], secret=ISS)
    assert body["user_id"] is None


def test_rate_limit_returns_429_after_limit(client):
    # fixture por función = fakeredis limpio; límite = 3 (settings de test)
    for _ in range(3):
        assert client.post("/api/auth/login").status_code == 200
    assert client.post("/api/auth/login").status_code == 429


def test_unknown_prefix_returns_502(client):
    resp = client.get("/api/unknown/thing",
                      headers={"Authorization": f"Bearer {_user_token()}"})
    assert resp.status_code == 502
