"""
Auth Service Configuration.
"""
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
import os
import re

_PLACEHOLDER_KEY = "your-secret-key-change-in-production"


class Settings(BaseSettings):
    """Auth service settings."""
    
    # Service info
    SERVICE_NAME: str = "auth-service"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Runtime environment (controls dev-only behaviors)
    # When ENVIRONMENT == "development" we can enable safe local shortcuts.
    ENVIRONMENT: str = "production"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/airedesk"
    DATABASE_SCHEMA: str = "public"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Internal/service JWT (refresh tokens, service tokens)
    SECRET_KEY: str = ""

    # JWT Settings
    DESK_SECRET_KEY: str = ""
    HUB_SECRET_KEY: str = ""
    NEST_SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 40  # 40 minutes
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # Encryption (Fernet key for password encryption)
    FERNET_KEY: str = ""
    # Legacy/alternative keys (para decrypt de passwords existentes)
    PASSWORD_FERNET_KEY: str = ""
    DESK_FERNET_KEY: str = ""
    HUB_FERNET_KEY: str = ""
    NEST_FERNET_KEY: str = ""
    
    # Rate limiting
    RATE_LIMIT_LOGIN: int = 5  # requests per minute
    RATE_LIMIT_RESET: int = 3  # requests per hour
    
    # CORS
    CORS_ORIGINS: List[str] = []
    # Base domain + any tenant subdomain, plus local dev. Custom tenant
    # domains (stored in tenant_domains) are not covered here.
    CORS_ORIGIN_REGEX: str = r"^https://([a-zA-Z0-9-]+\.)*airedesk\.com$|^http://localhost:3000$"
    
    # External services
    TENANT_SERVICE_URL: str = "http://tenant-service:8002"
    
    # Frontend URL for password reset links
    FRONTEND_URL: str = "http://localhost:3000"
    ARIA_TENANT_SLUG: str = "aria"

    # Google OAuth client credentials JSON (web/installed)
    GOOGLE_CREDENTIALS_JSON: Optional[str] = None
    
    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == _PLACEHOLDER_KEY:
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"



@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

