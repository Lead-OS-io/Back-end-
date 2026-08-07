"""add tenant_id, user_id, created_at to media_resources
Revision ID: 0002_media_owner
Revises: 0001_initial
Create Date: 2026-08-06 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002_media_owner"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_resources",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "media_resources",
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "media_resources",
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        op.f("ix_media_resources_tenant_id"),
        "media_resources",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_resources_user_id"),
        "media_resources",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_media_resources_user_id"), table_name="media_resources")
    op.drop_index(op.f("ix_media_resources_tenant_id"), table_name="media_resources")
    op.drop_column("media_resources", "created_at")
    op.drop_column("media_resources", "user_id")
    op.drop_column("media_resources", "tenant_id")
