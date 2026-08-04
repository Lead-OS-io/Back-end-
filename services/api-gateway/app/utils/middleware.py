import jwt
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.serializers.identity import IDENTITY_HEADERS, identity_headers_from_claims
from app.services.ratelimit import is_rate_limited
from app.utils.jwt_keys import decode_user_token
from shared.auth.service_token import mint_service_token

SECURITY_HEADERS = {
    "strict-transport-security": "max-age=63072000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}

PUBLIC_PATH_PREFIXES = (
    "/health",
    "/api/auth/login",
    "/api/auth/token",
    "/api/auth/register",
    "/api/auth/google",
    "/api/auth/password",
    "/media",
    "/tutorials",
)

_STRIP = tuple(h.lower() for h in IDENTITY_HEADERS)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RateLimitMiddleware:
    """Lee el redis de scope["app"].state.redis en runtime (los middlewares se
    configuran ANTES de que el lifespan pueble app.state)."""

    def __init__(self, app: ASGIApp, *, limit: int,
                 exempt_prefixes: tuple[str, ...] = ("/health",)):
        self.app = app
        self.limit = limit
        self.exempt_prefixes = exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(self.exempt_prefixes):
            await self.app(scope, receive, send)
            return
        redis_client = scope["app"].state.redis
        client_host = scope.get("client", ("unknown", 0))[0]
        if await is_rate_limited(redis_client, client_host, self.limit):
            response = JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class GatewayAuthMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        for name in _STRIP:
            if name in headers:
                del headers[name]

        path = scope["path"]
        served_locally = path.startswith(("/media", "/tutorials", "/health"))
        if not served_locally:
            headers["X-Service-Token"] = mint_service_token(
                secret=self.settings.INTER_SERVICE_SECRET, issuer="api-gateway"
            )

        if path.startswith(PUBLIC_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            await JSONResponse({"detail": "missing bearer token"}, status_code=401)(scope, receive, send)
            return
        try:
            claims = decode_user_token(auth.removeprefix("Bearer ").strip(), self.settings)
        except jwt.InvalidTokenError:
            await JSONResponse({"detail": "invalid token"}, status_code=401)(scope, receive, send)
            return

        for key, value in identity_headers_from_claims(claims).items():
            headers[key] = value
        await self.app(scope, receive, send)
