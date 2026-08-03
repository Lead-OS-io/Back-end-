"""
Tenant Service Configuration.
"""
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache
import os
import re


class Settings(BaseSettings):
    """Tenant service settings."""
    
    # Service info
    SERVICE_NAME: str = "tenant-service"
    SERVICE_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/airedesk"
    DATABASE_SCHEMA: str = "public"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
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
    
    # CORS
    CORS_ORIGINS: List[str] = []
    # Base domain + any tenant subdomain, plus local dev. Custom tenant
    # domains (stored in tenant_domains) are not covered here.
    CORS_ORIGIN_REGEX: str = r"^https://([a-zA-Z0-9-]+\.)*airedesk\.com$|^http://localhost:3000$"
    
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

