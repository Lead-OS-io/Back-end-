"""Structural tests: the backends we ship implement the StorageBackend Protocol."""
import inspect
import json

from app.storage import LocalBackend, MinioBackend
from app.storage.base import StorageBackend


def _protocol_methods(cls) -> set[str]:
    return {
        name
        for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_minio_backend_implements_protocol():
    assert hasattr(MinioBackend, "put_object")
    assert hasattr(MinioBackend, "get_object")
    assert hasattr(MinioBackend, "delete_object")
    assert hasattr(MinioBackend, "presigned_get_url")
    assert hasattr(MinioBackend, "ensure_bucket")
    assert hasattr(MinioBackend, "set_bucket_public")


def test_local_backend_implements_protocol():
    assert _protocol_methods(LocalBackend).issuperset(
        _protocol_methods(StorageBackend)
    )


def test_set_bucket_public_produces_valid_json(monkeypatch):
    captured: dict[str, str] = {}

    def fake_set_bucket_policy(self, bucket: str, policy: str) -> None:
        captured["bucket"] = bucket
        captured["policy"] = policy

    monkeypatch.setattr(
        "minio.Minio.set_bucket_policy",
        fake_set_bucket_policy,
    )

    backend = MinioBackend(
        endpoint="example:9000",
        root_user="u",
        root_password="p",
        secure=False,
    )
    backend.set_bucket_public(bucket="avatars", public=True)

    assert captured["bucket"] == "avatars"
    parsed = json.loads(captured["policy"])
    assert parsed["Statement"][0]["Resource"] == ["arn:aws:s3:::avatars/*"]
