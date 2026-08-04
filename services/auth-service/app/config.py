"""
Auth Service Configuration.
"""
from typing import Optional

from pydantic import field_validator

from shared.config.base import BaseServiceSettings

_PLACEHOLDER_KEY = "your-secret-key-change-in-production"


class Settings(BaseServiceSettings):
    """Auth service settings."""

    # Service info
    SERVICE_NAME: str = "auth-service"
    SERVICE_VERSION: str = "1.0.0"

    # Server
    PORT: int = 8001

    # Database
    DATABASE_SCHEMA: str = "public"

    # JWT Settings (clave única: SECRET_KEY)
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 40  # 40 minutes
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Encryption (Fernet key para passwords y refresh tokens de terceros)
    FERNET_KEY: str = ""

    # Rate limiting
    RATE_LIMIT_LOGIN: int = 5  # requests per minute
    RATE_LIMIT_RESET: int = 3  # requests per hour

    # External services
    TENANT_SERVICE_URL: str = "http://tenant-service:8002"

    # Frontend URL for password reset links
    FRONTEND_URL: str = "http://localhost:3000"

    # Google OAuth client credentials JSON (web/installed)
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == _PLACEHOLDER_KEY:
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v


settings = Settings()
