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
        "users",
        sa.Column("id", sqlmodel.sql.sqltypes.GUID(), nullable=False),
        sa.Column("tenant_id", sqlmodel.sql.sqltypes.GUID(), nullable=True),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("phone", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending_tenant", "active", "disabled", name="userstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_users_status"), "users", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_status"), table_name="users")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
