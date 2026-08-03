"""
Cases Service - Main Application Entry Point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import create_db_and_tables
from app.routes import router

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s | cases-service | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("cases_service.log")
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    
    logger.info(f"Starting {settings.SERVICE_NAME} v{settings.SERVICE_VERSION}")
    
    try:
        current_module = __import__("app.redis_client", fromlist=["init_redis", "close_redis"])
        current_module.init_redis()
        logger.info("Redis client initialized")
    except Exception as e:
        logger.error(f"Failed to init Redis: {e}")

    try:
        create_db_and_tables()
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
    
    yield
    
    try:
        await current_module.close_redis()
        logger.info("Redis client closed")
    except Exception as e:
        logger.error(f"Failed to close Redis: {e}")

    logger.info(f"Shutting down {settings.SERVICE_NAME}")


app = FastAPI(
    title="AireDesk Cases Service",
    description="Case management microservice",
    version=settings.SERVICE_VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


#
# IMPORTANT:
# - Desk internal clients historically call this service without the `/api` prefix.
# - The API gateway routes it under `/api/cases`.
# We serve BOTH prefixes to avoid breaking internal calls while enabling gateway-direct access.
#
app.include_router(router, prefix="", tags=["Cases"])
app.include_router(router, prefix="/api", tags=["Cases"])


@app.get("/health")
async def root_health():
    return {"status": "healthy", "service": settings.SERVICE_NAME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

