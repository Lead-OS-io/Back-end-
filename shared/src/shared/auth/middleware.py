import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from shared.auth.service_token import decode_service_token

EXEMPT_PATHS = frozenset({"/health"})


class ServiceTokenMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        secret: str,
        exempt_paths: frozenset[str] = EXEMPT_PATHS,
        exempt_prefixes: frozenset[str] = frozenset(),
    ):
        self.app = app
        self.secret = secret
        self.exempt_paths = exempt_paths
        self.exempt_prefixes = exempt_prefixes

    def _is_exempt(self, path: str) -> bool:
        if path in self.exempt_paths:
            return True
        return any(path.startswith(prefix) for prefix in self.exempt_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._is_exempt(scope["path"]):
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        token = headers.get(b"x-service-token", b"").decode()
        try:
            decode_service_token(token, secret=self.secret)
        except jwt.InvalidTokenError:
            response = JSONResponse({"detail": "invalid service token"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
