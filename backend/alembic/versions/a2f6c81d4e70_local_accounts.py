"""local accounts

Gives the user table room for accounts Muzikk owns itself. Jellyfin
installations are untouched: their rows keep a Jellyfin identifier and leave
the two new columns empty.

Revision ID: a2f6c81d4e70
Revises: f8a4d2b1c305
Create Date: 2026-09-20 18:05:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2f6c81d4e70"
down_revision: str | None = "f8a4d2b1c305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("username", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("password_hash", sa.Text(), nullable=True))
        # A local account has no Jellyfin identity to put here.
        batch_op.alter_column(
            "jellyfin_user_id", existing_type=sa.String(length=64), nullable=True
        )
    op.create_index("ix_user_username", "user", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_username", table_name="user")
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.alter_column(
            "jellyfin_user_id", existing_type=sa.String(length=64), nullable=False
        )
        batch_op.drop_column("password_hash")
        batch_op.drop_column("username")
