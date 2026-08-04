from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class ServiceHealth(BaseModel):
    name: str
    url: str
    healthy: bool
    detail: str | None = None


class ServicesHealthResponse(BaseModel):
    services: list[ServiceHealth]
