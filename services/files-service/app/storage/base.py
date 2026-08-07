"""Storage backend abstraction. Any object backend must implement this Protocol."""
from typing import Protocol


class StorageBackend(Protocol):
    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        size: int,
        content_type: str,
    ) -> None:
        ...

    def get_object(self, *, bucket: str, key: str) -> bytes:
        ...

    def delete_object(self, *, bucket: str, key: str) -> None:
        ...

    def presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_seconds: int,
    ) -> str:
        ...

    def ensure_bucket(self, *, bucket: str) -> None:
        ...

    def set_bucket_public(self, *, bucket: str, public: bool) -> None:
        ...
