import asyncio

import httpx
from fastapi import Request

HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
})
_RETRYABLE_STATUS = {502, 503, 504}
_IDEMPOTENT = {"GET", "HEAD"}


async def forward_request(client: httpx.AsyncClient, request: Request,
                          upstream_base: str) -> httpx.Response:
    url = f"{upstream_base}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    body = await request.body()
    return await client.request(request.method, url, headers=headers, content=body)


async def forward_with_retry(client: httpx.AsyncClient, request: Request,
                             upstream_base: str, *, attempts: int = 3,
                             backoff: float = 0.25) -> httpx.Response:
    can_retry = request.method in _IDEMPOTENT
    max_attempts = attempts if can_retry else 1
    for i in range(max_attempts):
        try:
            resp = await forward_request(client, request, upstream_base)
            if resp.status_code not in _RETRYABLE_STATUS or i == max_attempts - 1:
                return resp
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if i == max_attempts - 1:
                raise
        await asyncio.sleep(backoff * (2**i))
    raise RuntimeError("unreachable")  # pragma: no cover
