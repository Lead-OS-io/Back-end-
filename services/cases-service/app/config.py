"""
Cases Service Configuration.
"""
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator, Field
from functools import lru_cache
import os
import re


class Settings(BaseSettings):
    """Cases service settings."""
    
    SERVICE_NAME: str = "cases-service"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    HOST: str = "0.0.0.0"
    PORT: int = 8004
    
    DATABASE_URL: str = Field(default="postgresql://postgres:postgres@localhost:5432/airedesk", env="DATABASE_URL")
    DATABASE_SCHEMA: str = "public"
    
    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    
    # Inter-service communication
    AUTH_SERVICE_URL: str = "http://auth-service:8001"
    TENANT_SERVICE_URL: str = "http://tenant-service:8002"
    MAILING_SERVICE_URL: str = "http://mailing-service:8003"
    USERS_SERVICE_URL: str = "http://users-service:8005"
    PREMIUM_SERVICE_URL: str = "http://premium-service:8000"
    AGENCIES_SERVICE_URL: str = "http://agencies-service:8000"
    CARRIERS_SERVICE_URL: str = "http://carriers-service:8000"

    ENVIRONMENT: str = Field(default="production", env="ENVIRONMENT")
    
    CORS_ORIGINS: List[str] = []
    # Base domain + any tenant subdomain, plus local dev. Custom tenant
    # domains (stored in tenant_domains) are not covered here.
    CORS_ORIGIN_REGEX: str = r"^https://([a-zA-Z0-9-]+\.)*airedesk\.com$|^http://localhost:3000$"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _sanitize_database_url(cls, v):
        if not isinstance(v, str):
            return v
        s = v.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            s = s[1:-1]
        return s

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == "your-secret-key-change-in-production":
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

