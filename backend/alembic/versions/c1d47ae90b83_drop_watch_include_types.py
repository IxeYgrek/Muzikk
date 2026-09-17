"""drop watch include types

Revision ID: c1d47ae90b83
Revises: b5d2f81ac364
Create Date: 2026-09-12 17:24:08.113402

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c1d47ae90b83'
down_revision: str | None = 'b5d2f81ac364'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Kept from the days when following downloaded on its own, where limiting
    # the types was a safeguard. Nothing exposed it, and its default left every
    # single out of the Follow tab, which is exactly what a follower misses.
    with op.batch_alter_table('watched_artist', schema=None) as batch_op:
        batch_op.drop_column('include_types')


def downgrade() -> None:
    with op.batch_alter_table('watched_artist', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('include_types', sa.JSON(), nullable=False, server_default='[]')
        )
