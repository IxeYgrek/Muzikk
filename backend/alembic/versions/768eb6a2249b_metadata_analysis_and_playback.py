"""metadata analysis and playback

Revision ID: 768eb6a2249b
Revises: 4afec5977568
Create Date: 2026-09-08 23:08:05.249257

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '768eb6a2249b'
down_revision: str | None = '4afec5977568'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('metadata_album',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(length=1000), nullable=False),
    sa.Column('jellyfin_id', sa.String(length=64), nullable=True),
    sa.Column('album_artist', sa.String(length=500), nullable=False),
    sa.Column('album_title', sa.String(length=500), nullable=False),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('track_count', sa.Integer(), nullable=False),
    sa.Column('formats', sa.JSON(), nullable=False),
    sa.Column('fuzzy_key', sa.String(length=600), nullable=False),
    sa.Column('issues', sa.JSON(), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('has_cover', sa.Boolean(), nullable=False),
    sa.Column('release_mbid', sa.String(length=64), nullable=True),
    sa.Column('release_group_mbid', sa.String(length=64), nullable=True),
    sa.Column('tracks', sa.JSON(), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('match_release_group_mbid', sa.String(length=64), nullable=True),
    sa.Column('match_release_mbid', sa.String(length=64), nullable=True),
    sa.Column('match_artist', sa.String(length=500), nullable=False),
    sa.Column('match_title', sa.String(length=500), nullable=False),
    sa.Column('match_year', sa.Integer(), nullable=True),
    sa.Column('match_track_count', sa.Integer(), nullable=True),
    sa.Column('match_score', sa.Float(), nullable=False),
    sa.Column('match_source', sa.String(length=32), nullable=False),
    sa.Column('match_details', sa.JSON(), nullable=True),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('scanned_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('metadata_album', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_metadata_album_fuzzy_key'), ['fuzzy_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_metadata_album_jellyfin_id'), ['jellyfin_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_metadata_album_path'), ['path'], unique=True)
        batch_op.create_index(batch_op.f('ix_metadata_album_release_group_mbid'), ['release_group_mbid'], unique=False)
        batch_op.create_index(batch_op.f('ix_metadata_album_state'), ['state'], unique=False)
        batch_op.create_index('ix_metadata_state_artist', ['state', 'album_artist'], unique=False)

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('jellyfin_token', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('jellyfin_token')

    with op.batch_alter_table('metadata_album', schema=None) as batch_op:
        batch_op.drop_index('ix_metadata_state_artist')
        batch_op.drop_index(batch_op.f('ix_metadata_album_state'))
        batch_op.drop_index(batch_op.f('ix_metadata_album_release_group_mbid'))
        batch_op.drop_index(batch_op.f('ix_metadata_album_path'))
        batch_op.drop_index(batch_op.f('ix_metadata_album_jellyfin_id'))
        batch_op.drop_index(batch_op.f('ix_metadata_album_fuzzy_key'))

    op.drop_table('metadata_album')
