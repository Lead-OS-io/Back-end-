from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import Response

from app.config import Settings
from app.schemas.health import HealthResponse, ServiceHealth, ServicesHealthResponse
from app.services.media import file_response_with_range
from app.services.proxy import forward_with_retry
from shared.utils.exceptions import AppError

_HOP_BY_HOP_RESP = {"content-encoding", "transfer-encoding", "connection"}


def _resolve_upstream(settings: Settings, path: str) -> tuple[str | None, str]:
    """Return (upstream_base_url, gateway_prefix) for the request path."""
    routes = settings.service_routes
    matches = [p for p in routes if path == p or path.startswith(p + "/")]
    if not matches:
        return None, ""
    prefix = max(matches, key=len)
    return routes[prefix], prefix


def _upstream_path(settings: Settings, path: str, gateway_prefix: str) -> str:
    """Rewrite the gateway-facing path into the upstream service's path layout."""
    upstream_prefix = settings.rewrite_routes.get(gateway_prefix)
    if upstream_prefix is None:
        return path
    suffix = path[len(gateway_prefix):]
    return upstream_prefix + suffix


async def proxy_request(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    upstream, prefix = _resolve_upstream(settings, request.url.path)
    if upstream is None:
        raise AppError(502, f"no upstream configured for {request.url.path}")
    client: httpx.AsyncClient = request.app.state.http_client
    upstream_path = _upstream_path(settings, request.url.path, prefix)
    try:
        upstream_resp = await forward_with_retry(
            client, request, upstream, strip_path=upstream_path
        )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise AppError(502, "upstream unavailable")
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers={k: v for k, v in upstream_resp.headers.items()
                 if k.lower() not in _HOP_BY_HOP_RESP},
    )


async def health(request: Request) -> HealthResponse:
    return HealthResponse(status="ok", service=request.app.state.settings.SERVICE_NAME)


async def services_health(request: Request) -> ServicesHealthResponse:
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.http_client
    results: list[ServiceHealth] = []
    for name, url in settings.upstreams.items():
        try:
            resp = await client.get(f"{url}/health", timeout=3.0)
            results.append(ServiceHealth(name=name, url=url,
                                         healthy=resp.status_code == 200,
                                         detail=None if resp.status_code == 200 else f"status {resp.status_code}"))
        except httpx.HTTPError as exc:
            results.append(ServiceHealth(name=name, url=url, healthy=False, detail=str(exc)))
    return ServicesHealthResponse(services=results)


def media_file(relative: str, request: Request) -> Response:
    root = Path(request.app.state.settings.MEDIA_ROOT)
    return file_response_with_range(root, relative, request)
