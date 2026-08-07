import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.docs_aggregator.merger import merge_openapi


_ISS = "test-inter-service-secret"
_SECRET = "user-secret"


def _settings() -> Settings:
    return Settings(
        SERVICE_NAME="api-gateway",
        INTER_SERVICE_SECRET=_ISS,
        SECRET_KEY=_SECRET,
        REDIS_URL="redis://fake:6379/0",
        RATE_LIMIT_PER_MINUTE=1000,
    )


def _fake_openapi(service_name: str) -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": service_name, "version": "0.1.0"},
        "paths": {
            f"/{service_name}/api/auth/register": {
                "post": {
                    "summary": f"Register from {service_name}",
                    "responses": {"201": {"description": "created"}},
                }
            },
            f"/{service_name}/items": {
                "get": {
                    "summary": f"List items from {service_name}",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            f"/{service_name}/items/{{id}}": {
                "get": {"summary": "Get one", "responses": {"200": {"description": "ok"}}}
            },
        },
        "components": {
            "schemas": {
                f"{service_name}_Item": {"type": "object", "properties": {"id": {"type": "integer"}}}
            }
        },
    }


def _upstream_factory(specs: dict[str, dict]):
    async def _handler(request: httpx.Request) -> httpx.Response:
        for name, port in {
            "auth-service": 8001, "tenant-service": 8002, "files-service": 8004,
        }.items():
            if request.url.port == port and request.url.path == "/openapi.json":
                if name in specs:
                    return httpx.Response(200, json=specs[name])
        return httpx.Response(404)
    return _handler


@pytest.fixture
def aggregator_client():
    import fakeredis
    import fakeredis.aioredis

    specs = {name: _fake_openapi(name) for name in ("auth-service", "tenant-service", "files-service")}
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(_upstream_factory(specs)))
    app = create_app(
        _settings(),
        http_client=http_client,
        redis_client=fakeredis.aioredis.FakeRedis(
            decode_responses=True, server=fakeredis.FakeServer()
        ),
    )
    with TestClient(app) as c:
        yield c, specs


def test_merge_strips_service_prefix_and_keeps_paths_clean(aggregator_client):
    client, specs = aggregator_client
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    merged = resp.json()
    paths = merged["paths"]
    assert "/items" in paths
    assert "/items/{id}" in paths
    assert "/api/auth/register" in paths
    all_tags_in_items = {
        t for op in paths["/items"].values() for t in op.get("tags", [])
    }
    for svc in ("auth-service", "tenant-service", "files-service"):
        assert svc in all_tags_in_items


def test_merge_unions_schemas_without_overwriting(aggregator_client):
    client, _ = aggregator_client
    merged = client.get("/api/openapi.json").json()
    schemas = merged["components"]["schemas"]
    for name in ("auth-service_Item", "tenant-service_Item", "files-service_Item"):
        assert name in schemas


def test_aggregated_docs_is_html_and_swagger_referenced(aggregator_client):
    client, _ = aggregator_client
    resp = client.get("/api/docs")
    assert resp.status_code == 200
    assert "swagger-ui" in resp.text
    assert "/api/openapi.json" in resp.text


def test_aggregated_routes_are_public_without_bearer(aggregator_client):
    client, _ = aggregator_client
    assert client.get("/api/docs", headers={}).status_code == 200
    assert client.get("/api/openapi.json", headers={}).status_code == 200


def test_merge_openapi_empty_does_not_crash():
    out = merge_openapi({})
    assert out["openapi"] == "3.1.0"
    assert out["paths"] == {}
    assert out["components"]["schemas"] == {}
