import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.events import build_handlers
from app.router import router
from app.services.onboarding_completion import OnboardingCompletionRegistry
from shared.auth.middleware import ServiceTokenMiddleware
from shared.cache.client import create_redis
from shared.db.engine import create_service_engine, get_session_factory
from shared.events.bus import EventBus
from shared.events.consumer import Consumer
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_service_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        session_factory = get_session_factory(engine)
        redis = create_redis(settings.REDIS_URL)
        event_bus = EventBus(settings.REDIS_URL)
        completion_registry = OnboardingCompletionRegistry()
        app.state.session_factory = session_factory
        app.state.redis = redis
        app.state.event_bus = event_bus
        app.state.completion_registry = completion_registry
        app.state.settings = settings

        consumer = Consumer(
            settings.REDIS_URL,
            domain="onboarding",
            group="auth-service",
            consumer_name=f"auth-service-{settings.SERVICE_NAME}",
            handlers=build_handlers(session_factory, event_bus, completion_registry),
            block_ms=5000,
        )
        thread = threading.Thread(target=consumer.run_forever, daemon=True)
        thread.start()

        yield

        consumer.stop()
        thread.join(timeout=5)
        engine.dispose()

    app = FastAPI(title="auth-service", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=settings.INTER_SERVICE_SECRET)
    app.include_router(router, prefix="/api/auth")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
