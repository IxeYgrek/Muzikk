"""upgrade review

Revision ID: a1c7b4e93f52
Revises: 768eb6a2249b
Create Date: 2026-09-12 10:14:22.118903

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1c7b4e93f52'
down_revision: str | None = '768eb6a2249b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('upgrade_review', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('request', schema=None) as batch_op:
        batch_op.drop_column('upgrade_review')
