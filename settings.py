"""
Slim settings for the gateway shell (main.py).
Only what main.py actually reads — each microservice has its own app/config.py.
"""
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "AireDesk Backend"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    ENVIRONMENT: str = Field(default="production", env="ENVIRONMENT")
    BASE_URL: str = Field(default="localhost:8000", env="BASE_URL")

    ALLOWED_HOSTS: List[str] = Field(
        default=[
            "localhost", "127.0.0.1",
            "aria-desk.com", "*.aria-desk.com",
            "aire-helpdesk.com", "www.aire-helpdesk.com",
            "airedesk-dev.up.railway.app", "*.up.railway.app", "*.railway.app",
            "*.ngrok-free.app", "*.ngrok.io", "*.ngrok.app",
        ],
        env="ALLOWED_HOSTS",
    )
    CORS_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:3000", "https://localhost:3000",
            "https://aire-helpdesk.com", "https://www.aire-helpdesk.com",
            "https://airedesk-dev.up.railway.app",
        ],
        env="CORS_ORIGINS",
    )

    # Internal microservice URLs (patched at boot by main._resolve_internal_url)
    AUTH_SERVICE_URL: str = Field(default="http://127.0.0.1:8001", env="AUTH_SERVICE_URL")
    TENANT_SERVICE_URL: str = Field(default="http://127.0.0.1:8002", env="TENANT_SERVICE_URL")
    CASES_SERVICE_URL: str = Field(default="http://127.0.0.1:8004", env="CASES_SERVICE_URL")
    USERS_SERVICE_URL: str = Field(default="http://127.0.0.1:8005", env="USERS_SERVICE_URL")
    NEWS_SERVICE_URL: str = Field(default="http://127.0.0.1:8006", env="NEWS_SERVICE_URL")
    FILES_SERVICE_URL: str = Field(default="http://127.0.0.1:8011", env="FILES_SERVICE_URL")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
