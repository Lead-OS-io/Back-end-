"""
News service configuration
"""
import os
import re
from pydantic_settings import BaseSettings
from pydantic import field_validator

class Settings(BaseSettings):
    # App
    APP_NAME: str = "news-service"
    DEBUG: bool = False
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/monolith")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == "your-secret-key-change-in-production":
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v
    
    # CORS
    CORS_ORIGINS: list = []
    # Base domain + any tenant subdomain, plus local dev. Custom tenant
    # domains (stored in tenant_domains) are not covered here.
    CORS_ORIGIN_REGEX: str = r"^https://([a-zA-Z0-9-]+\.)*airedesk\.com$|^http://localhost:3000$"

    # Network
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8006"))
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()




