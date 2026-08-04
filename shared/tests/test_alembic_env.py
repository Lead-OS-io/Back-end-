from unittest.mock import MagicMock, patch

from sqlalchemy import MetaData

from shared.alembic.env_template import run_migrations


def test_run_migrations_offline_configures_url_and_metadata():
    metadata = MetaData()
    fake_context = MagicMock()
    fake_context.is_offline_mode.return_value = True

    with patch("shared.alembic.env_template.context", fake_context):
        run_migrations(lambda: "sqlite:///:memory:", metadata)

    fake_context.configure.assert_called_once()
    kwargs = fake_context.configure.call_args.kwargs
    assert kwargs["url"] == "sqlite:///:memory:"
    assert kwargs["target_metadata"] is metadata
    assert kwargs["compare_type"] is True
    fake_context.run_migrations.assert_called_once()


def test_run_migrations_online_uses_engine_from_url():
    metadata = MetaData()
    fake_context = MagicMock()
    fake_context.is_offline_mode.return_value = False

    with patch("shared.alembic.env_template.context", fake_context):
        run_migrations(lambda: "sqlite:///:memory:", metadata)

    fake_context.configure.assert_called_once()
    kwargs = fake_context.configure.call_args.kwargs
    assert kwargs["target_metadata"] is metadata
    assert kwargs["compare_type"] is True
    assert "connection" in kwargs
    fake_context.run_migrations.assert_called_once()
