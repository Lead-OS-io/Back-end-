"""MinIO backend for the StorageBackend Protocol. Wraps minio-py."""
import io
import json
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.storage.base import StorageBackend


class MinioBackend(StorageBackend):
    def __init__(
        self,
        *,
        endpoint: str,
        public_endpoint: str = "",
        root_user: str,
        root_password: str,
        secure: bool,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=root_user,
            secret_key=root_password,
            secure=secure,
        )
        self._public_endpoint = public_endpoint or endpoint

    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        size: int,
        content_type: str,
    ) -> None:
        self._client.put_object(
            bucket,
            key,
            io.BytesIO(data),
            size,
            content_type=content_type,
        )

    def get_object(self, *, bucket: str, key: str) -> bytes:
        resp = self._client.get_object(bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def delete_object(self, *, bucket: str, key: str) -> None:
        try:
            self._client.remove_object(bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return
            raise

    def presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_seconds: int,
    ) -> str:
        # The URL returned by minio-py is signed against the internal endpoint.
        # A simple host rewrite makes the URL invalid because AWS signature v4
        # covers the Host header. To produce a valid public URL we temporarily
        # point the existing client to the public endpoint, generate the
        # presigned URL, and then restore the internal endpoint. This keeps the
        # internal endpoint in use for all other SDK calls.
        if not self._public_endpoint or self._public_endpoint == self._client._base_url.host:
            return self._client.presigned_get_object(
                bucket, key, expires=timedelta(seconds=expires_seconds)
            )
        original_base_url = self._client._base_url
        from minio.helpers import BaseURL
        public_url = BaseURL(
            f"http://{self._public_endpoint}",
            region=original_base_url.region,
        )
        self._client._base_url = public_url
        try:
            url = self._client.presigned_get_object(
                bucket, key, expires=timedelta(seconds=expires_seconds)
            )
        finally:
            self._client._base_url = original_base_url
        return url

    def ensure_bucket(self, *, bucket: str) -> None:
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def set_bucket_public(self, *, bucket: str, public: bool) -> None:
        if public:
            policy = json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"AWS": ["*"]},
                            "Action": ["s3:GetObject"],
                            "Resource": [f"arn:aws:s3:::{bucket}/*"],
                        }
                    ],
                }
            )
            self._client.set_bucket_policy(bucket, policy)
        else:
            try:
                self._client.delete_bucket_policy(bucket)
            except S3Error as exc:
                if exc.code in {"NoSuchBucketPolicy", "NoSuchBucket"}:
                    return
                raise
