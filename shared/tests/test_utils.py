import logging
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.utils.exceptions import (
    AppError, ConflictError, ForbiddenError, NotFoundError, register_exception_handlers,
)
from shared.utils.logging import setup_logging


def test_setup_logging_configures_root_logger():
    setup_logging("test-service", level="DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert any("test-service" in (h.formatter._fmt or "") for h in root.handlers)


def test_app_error_maps_to_status_code():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/x")
    def x():
        raise NotFoundError("no existe")

    resp = TestClient(app).get("/x")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "no existe"}


def test_error_subclasses_status_codes():
    assert NotFoundError("x").status_code == 404
    assert ConflictError("x").status_code == 409
    assert ForbiddenError("x").status_code == 403
    assert AppError(418, "x").status_code == 418
