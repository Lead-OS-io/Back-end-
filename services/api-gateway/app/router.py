from fastapi import APIRouter, Request
from fastapi.responses import Response

from app import controller
from app.schemas.health import HealthResponse, ServicesHealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return await controller.health(request)


@router.get("/health/services", response_model=ServicesHealthResponse)
async def services_health(request: Request) -> ServicesHealthResponse:
    return await controller.services_health(request)


@router.get("/media/{file_path:path}")
async def media(file_path: str, request: Request) -> Response:
    return controller.media_file(file_path, request)


@router.get("/tutorials/{file_path:path}")
async def tutorials(file_path: str, request: Request) -> Response:
    return controller.media_file(f"tutorials/{file_path}", request)


@router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(request: Request) -> Response:
    return await controller.proxy_request(request)
