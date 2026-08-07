from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.internal_router import router as internal_router
from app.storage import get_storage
from shared.auth.middleware import ServiceTokenMiddleware
from shared.db.engine import create_service_engine, get_session_factory
from shared.utils.exceptions import register_exception_handlers
from shared.utils.logging import setup_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.SERVICE_NAME, "DEBUG" if settings.DEBUG else "INFO")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        storage = get_storage(settings)
        for bucket, is_public in settings.INIT_BUCKETS:
            storage.ensure_bucket(bucket=bucket)
            storage.set_bucket_public(bucket=bucket, public=is_public)
        engine = create_service_engine(settings.DATABASE_URL, echo=settings.DEBUG)
        app.state.session_factory = get_session_factory(engine)
        app.state.storage = storage
        app.state.settings = settings
        yield
        engine.dispose()

    app = FastAPI(title="files-service", lifespan=lifespan)
    register_exception_handlers(app)
    app.add_middleware(ServiceTokenMiddleware, secret=settings.INTER_SERVICE_SECRET)
    app.include_router(internal_router, prefix="/internal/files")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": settings.SERVICE_NAME}

    return app


app = create_app()
