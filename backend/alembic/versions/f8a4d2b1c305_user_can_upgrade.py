"""user can upgrade

Revision ID: f8a4d2b1c305
Revises: e7f3c9a1b204
Create Date: 2026-09-13 22:55:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8a4d2b1c305"
down_revision: str | None = "e7f3c9a1b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("can_upgrade", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Existing administrators already launch upgrades; keep that working
    # without a second pass on the users page.
    op.execute(sa.text('UPDATE "user" SET can_upgrade = 1 WHERE is_admin = 1'))


def downgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("can_upgrade")
