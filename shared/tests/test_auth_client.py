import httpx

from shared.auth.client import ServiceHttpClient
from shared.auth.service_token import decode_service_token

SECRET = "test-inter-service-secret"


def _capture_app(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"token": request.headers.get("x-service-token"),
                                     "other": request.headers.get("x-other")})


def test_client_injects_fresh_service_token_on_each_request():
    client = ServiceHttpClient(secret=SECRET, issuer="auth-service",
                               transport=httpx.MockTransport(_capture_app))
    r1 = client.get("http://tenant-service:8002/api/internal/tenants/active-ids")
    r2 = client.get("http://tenant-service:8002/api/internal/tenants/active-ids")
    for resp in (r1, r2):
        claims = decode_service_token(resp.json()["token"], secret=SECRET)
        assert claims["iss"] == "auth-service"


def test_client_preserves_caller_headers():
    client = ServiceHttpClient(secret=SECRET, issuer="auth-service",
                               transport=httpx.MockTransport(_capture_app))
    resp = client.get("http://x/", headers={"X-Other": "keep-me"})
    assert resp.json()["other"] == "keep-me"
