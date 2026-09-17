"""watched releases

Revision ID: b5d2f81ac364
Revises: a1c7b4e93f52
Create Date: 2026-09-12 15:02:41.550210

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b5d2f81ac364'
down_revision: str | None = 'a1c7b4e93f52'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'watched_release',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('watch_id', sa.Integer(), nullable=False),
        sa.Column('release_group_mbid', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('primary_type', sa.String(length=64), nullable=True),
        sa.Column('first_release_date', sa.String(length=16), nullable=True),
        sa.Column('is_new', sa.Boolean(), nullable=False),
        sa.Column('ignored', sa.Boolean(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['watch_id'], ['watched_artist.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('watch_id', 'release_group_mbid', name='uq_watched_release'),
    )
    op.create_index(
        op.f('ix_watched_release_watch_id'), 'watched_release', ['watch_id'], unique=False
    )
    op.create_index(
        op.f('ix_watched_release_release_group_mbid'),
        'watched_release',
        ['release_group_mbid'],
        unique=False,
    )

    # Following no longer downloads anything, so the automatic flag and the
    # memory of the releases already dealt with have nothing left to say: the
    # watched_release rows are that memory now.
    with op.batch_alter_table('watched_artist', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('scope', sa.String(length=16), nullable=False, server_default='new')
        )
        batch_op.drop_column('auto_download')
        batch_op.drop_column('seen_release_groups')


def downgrade() -> None:
    with op.batch_alter_table('watched_artist', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('seen_release_groups', sa.JSON(), nullable=False, server_default='[]')
        )
        batch_op.add_column(
            sa.Column('auto_download', sa.Boolean(), nullable=False, server_default=sa.text('0'))
        )
        batch_op.drop_column('scope')

    op.drop_index(op.f('ix_watched_release_release_group_mbid'), table_name='watched_release')
    op.drop_index(op.f('ix_watched_release_watch_id'), table_name='watched_release')
    op.drop_table('watched_release')
