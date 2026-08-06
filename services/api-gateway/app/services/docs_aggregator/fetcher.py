import json

import httpx
import redis.asyncio as aioredis
from fastapi import Request

from app.config import Settings
from shared.auth.service_token import mint_service_token


_CACHE_TTL_SECONDS = 60
_OPENAPI_PATH = "/openapi.json"


async def _fetch_one(client: httpx.AsyncClient, name: str, base_url: str,
                     redis: aioredis.Redis, service_secret: str) -> dict | None:
    cache_key = f"openapi:{name}"
    try:
        cached = await redis.get(cache_key)
    except Exception:
        cached = None
    if cached:
        return json.loads(cached)
    try:
        token = mint_service_token(secret=service_secret, issuer="api-gateway")
        resp = await client.get(
            f"{base_url}{_OPENAPI_PATH}",
            headers={"X-Service-Token": token},
            timeout=4.0,
        )
        resp.raise_for_status()
        spec = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    try:
        await redis.set(cache_key, json.dumps(spec), ex=_CACHE_TTL_SECONDS)
    except Exception:
        pass
    return spec


async def fetch_openapi_specs(request: Request) -> dict[str, dict]:
    settings: Settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.http_client
    redis: aioredis.Redis = request.app.state.redis
    out: dict[str, dict] = {}
    for name, url in settings.upstreams.items():
        spec = await _fetch_one(
            client, name, url, redis, settings.INTER_SERVICE_SECRET
        )
        if spec is not None:
            out[name] = spec
    return out
