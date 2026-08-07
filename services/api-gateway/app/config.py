from shared.config.base import BaseServiceSettings


class Settings(BaseServiceSettings):
    SERVICE_NAME: str = "api-gateway"
    PORT: int = 8000
    DATABASE_URL: str = ""  # el gateway no tiene DB

    AUTH_SERVICE_URL: str = "http://localhost:8001"
    TENANT_SERVICE_URL: str = "http://localhost:8002"
    FILES_SERVICE_URL: str = "http://localhost:8003"

    SECRET_KEY: str

    MEDIA_ROOT: str = "./media"
    RATE_LIMIT_PER_MINUTE: int = 100
    FRONTEND_URL: str = "http://localhost:3000"
    # Regex opcional para orígenes CORS del dominio de producción (vacío en dev)
    CORS_ORIGIN_REGEX: str = ""

    @property
    def service_routes(self) -> dict[str, str]:
        return {
            "/api/auth": self.AUTH_SERVICE_URL,
            "/api/tenants": self.TENANT_SERVICE_URL,
            "/api/files": self.FILES_SERVICE_URL,
            "/api/resolve": self.TENANT_SERVICE_URL,
        }

    @property
    def upstreams(self) -> dict[str, str]:
        return {
            "auth-service": self.AUTH_SERVICE_URL,
            "tenant-service": self.TENANT_SERVICE_URL,
            "files-service": self.FILES_SERVICE_URL,
        }
