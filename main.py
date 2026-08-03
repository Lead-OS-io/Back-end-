"""
Gateway shell: serves /health, static media, and proxies API traffic to the
internal microservices. The legacy desk_app monolith was removed — all business
logic lives in services/*.
"""
import asyncio
import logging
import mimetypes
import os
import re
import uuid
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, StreamingResponse
from uvicorn.config import LOGGING_CONFIG
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from settings import settings

LOGGING_CONFIG["loggers"]["uvicorn.error"]["level"] = "WARNING"
for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

public_base_url = (settings.BASE_URL or "").strip()
if public_base_url and not public_base_url.startswith(("http://", "https://")):
    public_base_url = f"https://{public_base_url}"
if not public_base_url:
    public_base_url = "http://localhost:8000"

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AireDesk API gateway. Business endpoints are served by the "
                "internal microservices (auth, users, cases, mailing, news, "
                "tenants, agencies, carriers, premium, files).",
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    servers=[
        {"url": "http://localhost:8000", "description": "Development server"},
        {"url": public_base_url, "description": "Production server"},
    ],
)


# =============================================================================
# Shared HTTP client (singleton) for proxying to internal services
# =============================================================================
class AsyncClientManager:
    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None:
            limits = httpx.Limits(
                max_connections=150,
                max_keepalive_connections=50,
                keepalive_expiry=4.0,  # below uvicorn's 5s drop to prevent RemoteProtocolError
            )
            cls._client = httpx.AsyncClient(
                timeout=httpx.Timeout(45.0, connect=10.0),
                limits=limits,
                headers={"X-Internal-Service": "monolith-desk"},
            )
        return cls._client

    @classmethod
    async def close_client(cls):
        if cls._client:
            await cls._client.aclose()
            cls._client = None


def get_http_client() -> httpx.AsyncClient:
    return AsyncClientManager.get_client()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        await AsyncClientManager.close_client()
    except Exception:
        pass


# =============================================================================
# Middleware
# =============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Security headers hardening:
    - Anti-clickjacking (X-Frame-Options DENY + CSP frame-ancestors)
    - X-Content-Type-Options nosniff
    - HSTS (max-age 1 year)
    - Strips framework-identifying headers
    - HTTP -> HTTPS redirect for public hostnames
    - Blocks TRACE/TRACK
    - Cache-Control per content type
    """

    async def dispatch(self, request, call_next):
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto") == "https"
        )

        # Only force HTTPS redirect for public hostnames (with a dot, not localhost).
        # Inside the Docker network, hostnames are service names and stay HTTP.
        hostname = (request.url.hostname or "").lower()
        is_internal_service_host = bool(hostname) and ("." not in hostname)
        if not is_https and hostname not in ["localhost", "127.0.0.1"] and not is_internal_service_host:
            https_url = str(request.url).replace("http://", "https://", 1)
            return RedirectResponse(url=https_url, status_code=301)

        if request.method in ["TRACE", "TRACK"]:
            return JSONResponse(
                status_code=405,
                content={"detail": "Method not allowed", "error_code": "METHOD_NOT_ALLOWED"},
            )

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        response = await call_next(request)

        for leaky_header in ["Server", "X-Powered-By", "X-AspNet-Version"]:
            if leaky_header in response.headers:
                del response.headers[leaky_header]

        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data: https:; "
                "script-src 'self' 'unsafe-inline'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"

        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["X-Request-ID"] = request_id

        if content_type.startswith("text/html") or "application/json" in content_type:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif any(content_type.startswith(ct) for ct in [
            "image/", "text/css", "application/javascript", "font/", "application/font"
        ]):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

        return response


app.add_middleware(SecurityHeadersMiddleware)

# Added LAST so it runs FIRST (resolves HTTPS scheme before SecurityHeaders/redirects)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")


# =============================================================================
# Static media (Railway volume or local ./media) with HTTP Range support
# =============================================================================
try:
    media_dir = os.getenv("MEDIA_ROOT", "media")

    # In Railway, /data is the persistent volume mount point.
    if not os.path.isabs(media_dir) and os.path.exists("/data"):
        media_dir = "/data/media"

    os.makedirs(media_dir, exist_ok=True)

    class RangeStaticFiles:
        """
        Minimal static file server with HTTP Range support (206).
        Required for HTML5 <video> seeking/streaming.
        """

        def __init__(self, directory: str, check_dir: bool = True):
            self.directory = os.path.abspath(directory)
            if check_dir and not os.path.isdir(self.directory):
                raise RuntimeError(f"Static directory does not exist: {self.directory}")

        def _safe_join(self, rel_path: str) -> str:
            rel = (rel_path or "").lstrip("/")
            full = os.path.abspath(os.path.normpath(os.path.join(self.directory, rel)))
            # Prevent path traversal
            if full != self.directory and not full.startswith(self.directory + os.sep):
                raise FileNotFoundError("Invalid path")
            return full

        @staticmethod
        def _iter_file(fp, length: int, chunk_size: int = 1024 * 1024):
            remaining = length
            while remaining > 0:
                data = fp.read(min(chunk_size, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

        @staticmethod
        def _parse_range(range_header: str, size: int) -> tuple[int, int] | None:
            if not range_header:
                return None
            if not range_header.startswith("bytes="):
                return None
            spec = range_header[len("bytes="):].strip()
            if "," in spec:
                # We only support single range
                spec = spec.split(",", 1)[0].strip()
            if "-" not in spec:
                return None
            start_s, end_s = spec.split("-", 1)
            start_s = start_s.strip()
            end_s = end_s.strip()

            if start_s == "":
                # suffix range: last N bytes
                try:
                    suffix = int(end_s)
                except Exception:
                    return None
                if suffix <= 0:
                    return None
                start = max(size - suffix, 0)
                end = size - 1
                return (start, end)

            try:
                start = int(start_s)
            except Exception:
                return None
            if start < 0:
                return None

            if end_s == "":
                end = size - 1
            else:
                try:
                    end = int(end_s)
                except Exception:
                    return None
            if start >= size:
                return None
            end = min(end, size - 1)
            if end < start:
                return None
            return (start, end)

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return
            method = (scope.get("method") or "GET").upper()
            if method not in ("GET", "HEAD"):
                resp = Response(status_code=405)
                await resp(scope, receive, send)
                return

            headers = Headers(scope=scope)
            rel_path = scope.get("path") or "/"
            try:
                full_path = self._safe_join(rel_path)
            except Exception:
                resp = Response(status_code=404)
                await resp(scope, receive, send)
                return

            if not os.path.exists(full_path) or not os.path.isfile(full_path):
                resp = Response(status_code=404)
                await resp(scope, receive, send)
                return

            size = os.path.getsize(full_path)
            content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"

            filename = os.path.basename(full_path)
            ext = os.path.splitext(filename)[1].lower()
            inline_exts = {
                ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
                ".mp4", ".webm", ".ogv", ".mov", ".m4v",
                ".mp3", ".ogg", ".wav",
            }
            content_disposition = None
            if ext not in inline_exts:
                content_disposition = f'attachment; filename="{filename}"'

            range_header = headers.get("range")
            byte_range = self._parse_range(range_header, size)

            common_headers = {"Accept-Ranges": "bytes"}
            if content_disposition:
                common_headers["Content-Disposition"] = content_disposition

            if byte_range:
                start, end = byte_range
                length = end - start + 1
                resp_headers = {
                    **common_headers,
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Content-Length": str(length),
                }
                if method == "HEAD":
                    resp = Response(status_code=206, media_type=content_type, headers=resp_headers)
                    await resp(scope, receive, send)
                    return
                fp = open(full_path, "rb")
                fp.seek(start)
                try:
                    resp = StreamingResponse(self._iter_file(fp, length), status_code=206, media_type=content_type, headers=resp_headers)
                    await resp(scope, receive, send)
                finally:
                    fp.close()
                return

            resp_headers = {**common_headers, "Content-Length": str(size)}
            if method == "HEAD":
                resp = Response(status_code=200, media_type=content_type, headers=resp_headers)
                if content_disposition:
                    resp.headers["Content-Disposition"] = content_disposition
                await resp(scope, receive, send)
                return

            fp = open(full_path, "rb")
            try:
                resp = StreamingResponse(self._iter_file(fp, size), status_code=200, media_type=content_type, headers=resp_headers)
                if content_disposition:
                    resp.headers["Content-Disposition"] = content_disposition
                await resp(scope, receive, send)
            finally:
                fp.close()

    app.mount("/media", RangeStaticFiles(directory=media_dir, check_dir=True), name="media")
    # Double mount for /api consistency (matches buildUrl in the frontend)
    app.mount("/api/media", RangeStaticFiles(directory=media_dir, check_dir=True), name="api_media")

    tutorials_dir = os.path.join(media_dir, "tutorials")
    if os.path.isdir(tutorials_dir):
        app.mount("/tutorials", RangeStaticFiles(directory=tutorials_dir, check_dir=True), name="tutorials")

except Exception:
    # Do not fail app startup if static mount fails
    pass


# =============================================================================
# DYNAMIC INTERNAL NETWORKING (Environment-Driven)
# =============================================================================
def _resolve_internal_url(service_name: str, default_port: int) -> str:
    """
    Resolves the URL for an internal microservice, respecting environment
    variables while correcting localhost/127.0.0.1 for Docker.
    """
    env_key = f"{service_name.upper()}_SERVICE_URL"
    # Priority: _INTERNAL env var > _URL env var (standard settings)
    url = os.getenv(f"{env_key}_INTERNAL") or os.getenv(env_key)
    if url:
        url = url.strip("\"'")

    # Translate to Docker service names ONLY in 'local' environment (Docker Compose dev).
    # In production (Railway) all services share the same container network (127.0.0.1).
    is_local = (os.getenv("ENVIRONMENT") or settings.ENVIRONMENT).lower() == "local"

    if not url:
        if is_local:
            return f"http://{service_name}-service:{default_port}"
        return f"http://127.0.0.1:{default_port}"

    # If the .env says localhost it works on host but fails inside Docker:
    # translate the host to the Docker service name, preserving the port.
    if is_local and ("localhost" in url or "127.0.0.1" in url):
        port_match = re.search(r':(\d+)', url)
        port = port_match.group(1) if port_match else str(default_port)
        url = f"http://{service_name}-service:{port}"

    return url


INTERNAL_SVC_NAMES = {
    "auth": 8001, "tenant": 8002, "cases": 8004, "users": 8005, "news": 8006, "files": 8011,
}

for s_name, s_port in INTERNAL_SVC_NAMES.items():
    s_url = _resolve_internal_url(s_name, s_port)
    setattr(settings, f"{s_name.upper()}_SERVICE_URL", s_url)
    logger.info(f"[BOOT] Internal service {s_name} mapped to {s_url}")


# =============================================================================
# PROXY ROUTES (local development without Docker/Traefik; in production
# Traefik routes these prefixes directly to the services)
# =============================================================================
@app.api_route("/api/google/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_google(request: Request, path: str):
    """Proxy Google OAuth requests to auth-service."""
    return await _proxy_request(request, f"{settings.AUTH_SERVICE_URL}/api/auth/google/{path}")


@app.api_route("/api/saas/webhooks/aria", methods=["POST"], tags=["Webhook"])
async def proxy_aria_webhook(request: Request):
    """Aria SaaS webhook -> users-service (owns provisioning + idempotency)."""
    return await _proxy_request(request, f"{settings.USERS_SERVICE_URL}/api/saas/webhooks/aria")


@app.api_route("/api/internal/tenants/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_tenant_service(request: Request, path: str):
    """Proxy internal requests to tenant-service using dynamic URL settings."""
    return await _proxy_request(request, f"{settings.TENANT_SERVICE_URL}/api/tenants/{path}")


@app.api_route("/api/cases/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_cases(request: Request, path: str):
    """Proxy case requests to cases-service."""
    return await _proxy_request(request, f"{settings.CASES_SERVICE_URL}/api/cases/{path}")


@app.api_route("/api/book-of-business/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_book_of_business(request: Request, path: str):
    """Proxy book-of-business requests to cases-service."""
    return await _proxy_request(request, f"{settings.CASES_SERVICE_URL}/api/book-of-business/{path}")


@app.api_route("/api/drafts/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_drafts(request: Request, path: str):
    """Proxy draft (case autosave) requests to cases-service."""
    return await _proxy_request(request, f"{settings.CASES_SERVICE_URL}/api/drafts/{path}")


@app.api_route("/api/medical/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_medical(request: Request, path: str):
    """Proxy medical reference data (medications/categories) requests to cases-service."""
    return await _proxy_request(request, f"{settings.CASES_SERVICE_URL}/api/medical/{path}")


# =============================================================================
# GENERIC INTERNAL PROXIES
# Maps /api/internal/{service}/* to the respective microservice port.
# =============================================================================
INTERNAL_SERVICES = {
    svc: getattr(settings, f"{svc.upper()}_SERVICE_URL")
    for svc in INTERNAL_SVC_NAMES.keys()
}


async def _generic_proxy_handler(request: Request, service: str, path: str):
    """
    Proxies requests to internal microservices using canonical microservice paths.
    Maps /api/internal/{service}/{path} -> microservice:port/api/{service}/{path}
    """
    base_url = INTERNAL_SERVICES.get(service)
    if not base_url:
        return Response(content="Service not found", status_code=404)

    target_url = f"{base_url}/api/{service}/{path}"
    return await _proxy_request(request, target_url)


for service_name in INTERNAL_SERVICES:
    # use default argument (s=service_name) to capture value in closure
    @app.api_route(f"/api/internal/{service_name}/{{path:path}}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
    async def proxy_internal_service(request: Request, path: str, s: str = service_name):
        return await _generic_proxy_handler(request, s, path)


async def _proxy_request(request: Request, target_url: str):
    """Generic proxy function with retry logic for transient errors."""
    request_id = getattr(request.state, 'request_id', 'unknown')

    query_string = str(request.url.query) if request.url.query else ""
    full_url = f"{target_url}?{query_string}" if query_string else target_url

    headers = dict(request.headers)
    headers.pop("host", None)

    body = await request.body() if request.method not in ["GET", "HEAD", "OPTIONS"] else None

    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            client = get_http_client()
            response = await client.request(
                method=request.method,
                url=full_url,
                headers=headers,
                content=body,
            )
            # Important: do NOT forward hop-by-hop or size/encoding headers.
            excluded_headers = {
                "connection",
                "keep-alive",
                "proxy-authenticate",
                "proxy-authorization",
                "te",
                "trailers",
                "transfer-encoding",
                "upgrade",
                "content-length",
                "content-encoding",
            }
            out_headers = {
                k: v for (k, v) in response.headers.items()
                if k.lower() not in excluded_headers
            }
            content_type = response.headers.get("content-type")
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=out_headers,
                media_type=content_type,
            )
        except (httpx.RemoteProtocolError, httpx.ReadTimeout) as exc:
            if attempt < max_retries:
                logger.warning(
                    f"[{request_id}] Proxy transient error on attempt {attempt + 1}/{max_retries + 1} "
                    f"to {target_url}: {type(exc).__name__}: {exc}. Retrying..."
                )
                await asyncio.sleep(0.5 * (attempt + 1))  # Backoff: 0.5s, 1s
                continue
            logger.error(
                f"[{request_id}] Proxy failed after {max_retries + 1} attempts "
                f"to {target_url}: {type(exc).__name__}: {exc}"
            )
            return Response(
                content='{"detail":"Service temporarily unavailable. Please retry.","error_code":"BAD_GATEWAY"}',
                status_code=502,
                media_type="application/json",
            )
        except httpx.ConnectError:
            return Response(
                content='{"detail":"Service not available","error_code":"SERVICE_UNAVAILABLE"}',
                status_code=503,
                media_type="application/json",
            )
        except httpx.HTTPError as exc:
            logger.error(
                f"[{request_id}] Proxy HTTP error to {target_url}: {type(exc).__name__}: {exc}"
            )
            return Response(
                content='{"detail":"Bad gateway","error_code":"BAD_GATEWAY"}',
                status_code=502,
                media_type="application/json",
            )


# =============================================================================
# Exception handlers
# =============================================================================
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    request_id = getattr(request.state, 'request_id', 'unknown')
    logging.getLogger("uvicorn.error").info(f"[{request_id}] 404 Not Found: {request.url}")
    detail = getattr(exc, "detail", "Resource not found")
    return JSONResponse(
        status_code=404,
        content={"detail": detail, "error_code": "NOT_FOUND"},
    )


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc):
    request_id = getattr(request.state, 'request_id', 'unknown')
    logging.getLogger("uvicorn.error").info(f"[{request_id}] 405 Method Not Allowed: {request.method} {request.url}")
    return JSONResponse(
        status_code=405,
        content={"detail": "Method not allowed", "error_code": "METHOD_NOT_ALLOWED"},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, 'request_id', 'unknown')
    err_logger = logging.getLogger("uvicorn.error")
    err_logger.error(f"[{request_id}] Unhandled exception: {str(exc)}")
    import traceback
    err_logger.error(f"[{request_id}] Traceback: {traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_code": "INTERNAL_ERROR"},
    )


# =============================================================================
# System endpoints
# =============================================================================
@app.get(
    "/health",
    summary="Health Check",
    description="Check if the API is running and healthy",
    tags=["System"],
)
async def health_check(request: Request):
    return {
        "status": "healthy",
        "version": settings.VERSION,
    }


@app.get(
    "/",
    summary="API Root",
    description="Get API information and documentation links",
    tags=["System"],
)
async def root():
    return {
        "message": "AireDesk Backend API",
        "version": settings.VERSION,
        "docs": "/api/docs",
        "redoc": "/api/redoc",
        "openapi": "/api/openapi.json",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_config=LOGGING_CONFIG,
    )
