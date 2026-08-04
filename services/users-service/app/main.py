from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI

from app.config import Settings
from app.events import HANDLERS
from app.router import router
from shared.cache.client import create_redis
from shared.auth.middleware import ServiceTokenMiddleware
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
        app.state.session_factory = get_session_factory(engine)
        app.state.redis = create_redis(settings.REDIS_URL)
        app.state.event_bus = EventBus(settings.REDIS_URL)
        app.state.settings = settings

        consumer = Consumer(
            settings.REDIS_URL,
            domain="auth",
            group="users-service",
            consumer_name=f"users-service-{settings.SERVICE_NAME}",
            handlers=HANDLERS,
        )
        thread = threading.Thread(target=consumer.run_forever, daemon=True)
        thread.start()
        yield
        consumer.stop()
        thread.join(timeout=5)
        engine.dispose()

    app = FastAPI(title="users-service", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=settings.INTER_SERVICE_SECRET)
    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
