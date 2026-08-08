"""Storage backend factory."""
from app.config import Settings
from app.storage.base import StorageBackend
from app.storage.local_backend import LocalBackend
from app.storage.minio_backend import MinioBackend


def get_storage(settings: Settings) -> StorageBackend:
    backend = settings.STORAGE_BACKEND.lower()
    if backend == "minio":
        return MinioBackend(
            endpoint=settings.MINIO_ENDPOINT,
            public_endpoint=settings.MINIO_PUBLIC_ENDPOINT,
            root_user=settings.MINIO_ROOT_USER,
            root_password=settings.MINIO_ROOT_PASSWORD,
            secure=settings.MINIO_SECURE,
        )
    if backend == "local":
        return LocalBackend()
    raise ValueError(
        f"unknown STORAGE_BACKEND='{settings.STORAGE_BACKEND}'; "
        "supported values: minio, local"
    )


__all__ = ["StorageBackend", "get_storage"]
