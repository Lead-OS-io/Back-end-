"""
Tenant Service Configuration.
"""
from typing import List
from pydantic import field_validator

from shared.config.base import BaseServiceSettings


class Settings(BaseServiceSettings):
    """Tenant service settings."""

    # Service info
    SERVICE_NAME: str = "tenant-service"
    SERVICE_VERSION: str = "1.0.0"

    # Server
    PORT: int = 8002

    # Database
    DATABASE_SCHEMA: str = "public"

    # JWT (for validating auth tokens)
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"

    # Cloudflare
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""

    # Domain settings
    BASE_DOMAIN: str = "airedesk.com"
    CNAME_TARGET: str = "customers.airedesk.com"

    # CORS (lo aplica el gateway; se conserva por compat de config)
    CORS_ORIGINS: List[str] = []
    CORS_ORIGIN_REGEX: str = r"^https://([a-zA-Z0-9-]+\.)*airedesk\.com$|^http://localhost:3000$"

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == "your-secret-key-change-in-production":
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v


settings = Settings()
