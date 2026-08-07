"""Local-disk backend. Not implemented yet; this exists to enforce the
'only MinIO today' decision. Swap in a real implementation if needed later."""
from app.storage.base import StorageBackend


class LocalBackend(StorageBackend):
    def put_object(self, *, bucket: str, key: str, data: bytes,
                   size: int, content_type: str) -> None:
        raise NotImplementedError(
            "local filesystem backend is not implemented; use STORAGE_BACKEND=minio"
        )

    def get_object(self, *, bucket: str, key: str) -> bytes:
        raise NotImplementedError(
            "local filesystem backend is not implemented; use STORAGE_BACKEND=minio"
        )

    def delete_object(self, *, bucket: str, key: str) -> None:
        raise NotImplementedError(
            "local filesystem backend is not implemented; use STORAGE_BACKEND=minio"
        )

    def presigned_get_url(self, *, bucket: str, key: str, expires_seconds: int) -> str:
        raise NotImplementedError(
            "local filesystem backend is not implemented; use STORAGE_BACKEND=minio"
        )

    def ensure_bucket(self, *, bucket: str) -> None:
        raise NotImplementedError(
            "local filesystem backend is not implemented; use STORAGE_BACKEND=minio"
        )

    def set_bucket_public(self, *, bucket: str, public: bool) -> None:
        raise NotImplementedError(
            "local filesystem backend is not implemented; use STORAGE_BACKEND=minio"
        )
