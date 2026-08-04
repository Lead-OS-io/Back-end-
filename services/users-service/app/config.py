"""
User service configuration
"""
from typing import Optional

from pydantic import field_validator

from shared.config.base import BaseServiceSettings


class Settings(BaseServiceSettings):
    # App
    SERVICE_NAME: str = "users-service"
    PORT: int = 8003

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://x:x@localhost:5432/users_db"

    # Security
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == "your-secret-key-change-in-production":
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v

    # Inter-service
    AUTH_SERVICE_URL: str = "http://auth-service:8001"

    # Google (Calendar)
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None


settings = Settings()
