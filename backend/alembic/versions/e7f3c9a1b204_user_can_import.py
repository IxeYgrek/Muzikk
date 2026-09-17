"""user can import

Revision ID: e7f3c9a1b204
Revises: c1d47ae90b83
Create Date: 2026-09-13 10:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f3c9a1b204"
down_revision: str | None = "c1d47ae90b83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("can_import", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Existing administrators would otherwise find the drop zone locked after
    # the upgrade, with no other account able to grant them the right.
    op.execute(sa.text('UPDATE "user" SET can_import = 1 WHERE is_admin = 1'))


def downgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("can_import")
