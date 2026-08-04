"""
Files service configuration
"""
from pydantic import field_validator

from shared.config.base import BaseServiceSettings


class Settings(BaseServiceSettings):
    # App
    SERVICE_NAME: str = "files-service"
    PORT: int = 8004

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://x:x@localhost:5432/files_db"

    # Security
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v):
        if not v or v == "your-secret-key-change-in-production":
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v

    # Storage
    STORAGE_PATH: str = "./storage"
    MAX_FILE_SIZE: int = 500 * 1024 * 1024  # 500 MB
    ALLOWED_EXTENSIONS: list = [
        "jpg", "jpeg", "png", "gif", "webp",  # Images
        "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt",  # Documents
        "mp4", "mov", "avi", "mkv", "webm"  # Videos
    ]

    # CORS (lo aplica el gateway; se conserva por compat de config)
    CORS_ORIGINS: list = []
    CORS_ORIGIN_REGEX: str = r"^https://([a-zA-Z0-9-]+\.)*airedesk\.com$|^http://localhost:3000$"


settings = Settings()
