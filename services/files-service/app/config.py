"""Files service configuration."""
import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

from shared.config.base import BaseServiceSettings


class Settings(BaseServiceSettings):
    SERVICE_NAME: str = "files-service"
    PORT: int = 8004
    DATABASE_SCHEMA: str = "public"

    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"

    STORAGE_BACKEND: str = "minio"
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_PUBLIC_ENDPOINT: str = "localhost:9000"
    MINIO_ROOT_USER: str = "minioadmin"
    MINIO_ROOT_PASSWORD: str = "minioadmin"
    MINIO_SECURE: bool = False
    MINIO_BUCKET: str = "media"

    INIT_BUCKETS: tuple[tuple[str, bool], ...] = ()
    INIT_BUCKETS_JSON: str = ""
    PRESIGN_TTL_SECONDS: int = 300
    AVATAR_MAX_BYTES: int = 5 * 1024 * 1024
    AVATAR_ALLOWED_MIMETYPES: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("INIT_BUCKETS", mode="before")
    @classmethod
    def _decode_buckets(cls, value: Any) -> tuple[tuple[str, bool], ...]:
        if isinstance(value, str):
            parsed = json.loads(value)
            return tuple((name, bool(is_public)) for name, is_public in parsed)
        return value

    @field_validator("AVATAR_ALLOWED_MIMETYPES", mode="before")
    @classmethod
    def _split_mimetypes(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(v.strip() for v in value.split(",") if v.strip())
        return value

    @field_validator("SECRET_KEY")
    @classmethod
    def _require_secret_key(cls, v: str) -> str:
        if not v or v == "your-secret-key-change-in-production":
            raise ValueError("SECRET_KEY env var is required and must not use the placeholder value")
        return v

    def model_post_init(self, __context: Any) -> None:
        if not self.INIT_BUCKETS and self.INIT_BUCKETS_JSON:
            self.INIT_BUCKETS = self._decode_buckets(self.INIT_BUCKETS_JSON)


settings = Settings()
