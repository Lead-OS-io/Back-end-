# users-service has no models in the clean-slate phase.
# This file exists so Alembic can locate env.py; the service
# has no schema to migrate.
from shared.alembic.env_template import run_migrations  # noqa: F401

# run_migrations is unused here but the import is kept so the module
# loads cleanly. With no target_metadata, Alembic would error on
# `alembic upgrade head`, so the Dockerfile's CMD must NOT run alembic
# for this service. See Dockerfile.dev comment.