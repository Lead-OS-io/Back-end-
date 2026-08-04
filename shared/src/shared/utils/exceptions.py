from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class NotFoundError(AppError):
    def __init__(self, detail: str = "not found"):
        super().__init__(404, detail)


class ConflictError(AppError):
    def __init__(self, detail: str = "conflict"):
        super().__init__(409, detail)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "forbidden"):
        super().__init__(403, detail)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
