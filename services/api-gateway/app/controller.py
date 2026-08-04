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


def _resolve_upstream(settings: Settings, path: str) -> str | None:
    routes = settings.service_routes
    matches = [p for p in routes if path == p or path.startswith(p + "/")]
    if not matches:
        return None
    return routes[max(matches, key=len)]


async def proxy_request(request: Request) -> Response:
    settings: Settings = request.app.state.settings
    upstream = _resolve_upstream(settings, request.url.path)
    if upstream is None:
        raise AppError(502, f"no upstream configured for {request.url.path}")
    client: httpx.AsyncClient = request.app.state.http_client
    try:
        upstream_resp = await forward_with_retry(client, request, upstream)
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
