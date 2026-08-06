"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-05 00:00:00.000000
"""
import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sqlmodel.sql.sqltypes.GUID(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("slug", sqlmodel.sql.sqltypes.AutoString(length=63), nullable=False),
        sa.Column("business_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("timezone", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("legal_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("support_inbox", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("trial", "active", "suspended", "cancelled", name="tenantstatus"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)
    op.create_index(op.f("ix_tenants_status"), "tenants", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tenants_status"), table_name="tenants")
    op.drop_index(op.f("ix_tenants_slug"), table_name="tenants")
    op.drop_table("tenants")
