import pytest

from shared.config.base import BaseServiceSettings


class _SvcSettings(BaseServiceSettings):
    MY_OWN_FIELD: str = "default"


def test_reads_env_and_service_fields(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "auth-service")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@h/auth_db")
    monkeypatch.setenv("INTER_SERVICE_SECRET", "s3cr3t")
    s = _SvcSettings()
    assert s.SERVICE_NAME == "auth-service"
    assert s.PORT == 8000
    assert s.REDIS_URL == "redis://localhost:6379/0"
    assert s.MY_OWN_FIELD == "default"


def test_missing_required_fields_raise(monkeypatch):
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("INTER_SERVICE_SECRET", raising=False)
    monkeypatch.chdir("/tmp")  # lejos de cualquier .env
    with pytest.raises(Exception):
        _SvcSettings(_env_file=None)
