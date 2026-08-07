"""drop users.avatar_media_id

The avatar FK lived in auth_db only as a convenience pointer; ownership now
lives in files_db.media_resources.user_id. Removing this column completes
the decoupling of auth-service from files-service (no cross-DB FK).
Revision ID: 0003_drop_avatar_media_id
Revises: 0002_refresh_tokens_and_avatar
Create Date: 2026-08-07 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003_drop_avatar_media_id"
down_revision = "0002_refresh_tokens_and_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "avatar_media_id")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("avatar_media_id", UUID(as_uuid=True), nullable=True),
    )
