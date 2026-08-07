"""MediaManager: orchestrates a StorageBackend with the DB rows."""
import re
import secrets
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models.entities import MediaResources
from app.models.enums import MediaPurpose, MediaType
from app.storage.base import StorageBackend


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    cleaned = _UNSAFE.sub("_", name).strip("._-")
    return cleaned or "file"


class MediaManager:
    AVATAR_BUCKET = "avatars"

    def __init__(self, db: Session, backend: StorageBackend) -> None:
        self._db = db
        self._backend = backend

    def upload_avatar(
        self,
        *,
        tenant_id: Optional[uuid.UUID],
        user_id: uuid.UUID,
        content: bytes,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> MediaResources:
        ext = (filename.rsplit(".", 1)[-1] or "bin").lower()[:8]
        random_suffix = secrets.token_urlsafe(8)
        key = f"users/{user_id}/{datetime.utcnow():%Y%m%d}-{random_suffix}.{ext}"

        existing = self.get_avatar(user_id=user_id)
        if existing is not None:
            self._backend.delete_object(bucket=existing.bucket, key=existing.path)
            self._db.delete(existing)
            self._db.commit()

        row = MediaResources(
            tenant_id=tenant_id,
            user_id=user_id,
            purpose=MediaPurpose.PROFILE_PHOTO,
            media_type=MediaType.IMAGE,
            mimetype=content_type,
            format=ext,
            size_bytes=size_bytes,
            original_filename=filename,
            bucket=self.AVATAR_BUCKET,
            path=key,
            is_public=False,
            meta={
                "content_type": content_type,
                "extension": ext,
                "replaced_at": datetime.utcnow().isoformat(),
            },
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)

        self._backend.put_object(
            bucket=row.bucket,
            key=key,
            data=content,
            size=size_bytes,
            content_type=content_type,
        )
        return row

    def get_avatar(self, *, user_id: uuid.UUID) -> Optional[MediaResources]:
        statement = select(MediaResources).where(
            MediaResources.user_id == user_id,
            MediaResources.purpose == MediaPurpose.PROFILE_PHOTO,
        )
        return self._db.exec(statement).first()

    def delete_avatar(self, *, user_id: uuid.UUID) -> bool:
        existing = self.get_avatar(user_id=user_id)
        if existing is None:
            return False
        self._backend.delete_object(bucket=existing.bucket, key=existing.path)
        self._db.delete(existing)
        self._db.commit()
        return True

    def presigned_url_for(
        self, *, media: MediaResources, ttl_seconds: int = 300
    ) -> str:
        return self._backend.presigned_get_url(
            bucket=media.bucket, key=media.path, expires_seconds=ttl_seconds,
        )


__all__ = ["MediaManager"]
