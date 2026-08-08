import httpx
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport

from app.services.proxy import forward_request, forward_with_retry


def _scope_request(method: str, path: str, headers: dict, body: bytes = b"") -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "method": method, "path": path, "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }, receive=receive)


@pytest.mark.asyncio
async def test_forward_request_strips_hop_by_hop_headers():
    seen = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.headers))
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    req = _scope_request("GET", "/api/legacy/users", {"Host": "gateway", "X-Other": "keep",
                                                        "Connection": "close"})
    resp = await forward_request(client, req, "http://auth-service:8001")
    assert resp.status_code == 200
    assert seen.get("x-other") == "keep"
    # Los hop-by-hop del cliente no se reenvían: host del upstream, no "gateway";
    # httpx 0.27 añade su propio connection: keep-alive (transport-level).
    assert seen.get("host") == "auth-service:8001"
    assert seen.get("connection") != "close"


@pytest.mark.asyncio
async def test_retry_on_503_then_success():
    calls = {"n": 0}

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503 if calls["n"] < 3 else 200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    req = _scope_request("GET", "/api/legacy/users", {})
    resp = await forward_with_retry(client, req, "http://auth-service:8001", backoff=0)
    assert resp.status_code == 200 and calls["n"] == 3


@pytest.mark.asyncio
async def test_no_retry_on_post():
    calls = {"n": 0}

    async def upstream(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    req = _scope_request("POST", "/api/legacy/users", {})
    resp = await forward_with_retry(client, req, "http://auth-service:8001", backoff=0)
    assert resp.status_code == 503 and calls["n"] == 1


@pytest.mark.asyncio
async def test_forward_request_uses_strip_path_when_configured():
    seen_path = None

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal seen_path
        seen_path = request.url.path
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    req = _scope_request("POST", "/api/files/users/me/avatar", {})
    resp = await forward_request(
        client, req, "http://files-service:8004", strip_path="/public/files/users/me/avatar"
    )
    assert resp.status_code == 200
    assert seen_path == "/public/files/users/me/avatar"
