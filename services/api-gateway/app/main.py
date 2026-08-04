from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.router import router
from app.utils.middleware import (
    GatewayAuthMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware,
)
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None, *,
               http_client: httpx.AsyncClient | None = None,
               redis_client=None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.http_client = http_client or httpx.AsyncClient(
            limits=httpx.Limits(max_connections=150), timeout=httpx.Timeout(45.0)
        )
        app.state.redis = redis_client or aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        yield
        await app.state.http_client.aclose()
        await app.state.redis.aclose()

    app = FastAPI(title="lead-os api-gateway", lifespan=lifespan)
    register_exception_handlers(app)

    app.add_middleware(GatewayAuthMiddleware, settings=settings)
    app.add_middleware(RateLimitMiddleware, limit=settings.RATE_LIMIT_PER_MINUTE)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
        allow_origin_regex=r"https://.*\.airedesk\.com",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)
    return app


app = create_app()
