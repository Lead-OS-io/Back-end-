"""
Auth Service Configuration.
"""
from typing import Optional, Tuple

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

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
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour (login service)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Encryption (Fernet key para passwords y refresh tokens de terceros)
    FERNET_KEY: str = ""

    # Rate limiting
    RATE_LIMIT_LOGIN: int = 5  # requests per minute
    RATE_LIMIT_RESET: int = 3  # requests per hour

    # External services
    TENANT_SERVICE_URL: str = "http://tenant-service:8002"
    FILES_SERVICE_URL: str = "http://files-service:8004"

    # Avatar configuration
    AVATAR_MAX_BYTES: int = 5 * 1024 * 1024
    AVATAR_ALLOWED_MIMETYPES: Tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")
    PRESIGN_TTL_SECONDS: int = 300

    # Frontend URL for password reset links
    FRONTEND_URL: str = "http://localhost:3000"

    # Google OAuth client credentials JSON (web/installed)
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == _PLACEHOLDER_KEY:
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v

    @field_validator("AVATAR_ALLOWED_MIMETYPES", mode="before")
    @classmethod
    def _split_avatar_mimetypes(cls, value):
        if isinstance(value, str):
            return tuple(v.strip() for v in value.split(",") if v.strip())
        return value


settings = Settings()
