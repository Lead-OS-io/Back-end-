"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-05 00:00:00.000000
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The SAEnum instances below are referenced by the table columns.
    # SQLAlchemy will auto-create the PostgreSQL ENUM types when the
    # table is created (via _on_table_create). We do NOT call
    # `.create(bind=..., checkfirst=True)` here because doing so creates
    # the types twice and the second attempt fails with DuplicateObject.
    media_type = sa.Enum(
        "image", "video", "audio", "document", "other", name="media_type",
        create_type=False,
    )
    media_purpose = sa.Enum(
        "product_image", "category_image", "profile_photo", "payment_receipt",
        "banner_video", "other", name="media_purpose",
        create_type=False,
    )

    op.create_table(
        "media_resources",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("media_type", media_type, nullable=False),
        sa.Column("purpose", media_purpose, nullable=False),
        sa.Column("mimetype", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("format", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("bucket", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_media_resources_media_type"), "media_resources", ["media_type"], unique=False)
    op.create_index(op.f("ix_media_resources_purpose"), "media_resources", ["purpose"], unique=False)
    op.create_index(op.f("ix_media_resources_is_public"), "media_resources", ["is_public"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_media_resources_is_public"), table_name="media_resources")
    op.drop_index(op.f("ix_media_resources_purpose"), table_name="media_resources")
    op.drop_index(op.f("ix_media_resources_media_type"), table_name="media_resources")
    op.drop_table("media_resources")
    # Drop the enum types explicitly after the table is dropped.
    op.execute("DROP TYPE IF EXISTS media_purpose")
    op.execute("DROP TYPE IF EXISTS media_type")