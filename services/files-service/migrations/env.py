from app.config import settings  # noqa: E402
from app.models import *  # noqa: F401,F403,E402  (registra todos los modelos en metadata)
from sqlmodel import SQLModel  # noqa: E402

from shared.alembic.env_template import run_migrations  # noqa: E402

run_migrations(lambda: settings.DATABASE_URL, SQLModel.metadata)
