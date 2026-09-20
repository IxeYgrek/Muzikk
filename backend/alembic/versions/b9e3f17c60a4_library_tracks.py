"""library tracks

The table the local scanner fills, one row per audio file. Jellyfin
installations never write to it: their tracklists come from Jellyfin.

Revision ID: b9e3f17c60a4
Revises: a2f6c81d4e70
Create Date: 2026-09-20 18:10:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9e3f17c60a4"
down_revision: str | None = "a2f6c81d4e70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_track",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("album_item_id", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("artist", sa.String(length=500), nullable=False),
        sa.Column("album", sa.String(length=500), nullable=False),
        sa.Column("track", sa.Integer(), nullable=True),
        sa.Column("disc", sa.Integer(), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("container", sa.String(length=16), nullable=False),
        sa.Column("is_lossless", sa.Boolean(), nullable=False),
        sa.Column("recording_mbid", sa.String(length=64), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mtime", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_library_track_item_id", "library_track", ["item_id"], unique=True)
    op.create_index("ix_library_track_path", "library_track", ["path"], unique=True)
    op.create_index("ix_library_track_album_item_id", "library_track", ["album_item_id"])
    op.create_index(
        "ix_library_track_album_order", "library_track", ["album_item_id", "disc", "track"]
    )


def downgrade() -> None:
    op.drop_index("ix_library_track_album_order", table_name="library_track")
    op.drop_index("ix_library_track_album_item_id", table_name="library_track")
    op.drop_index("ix_library_track_path", table_name="library_track")
    op.drop_index("ix_library_track_item_id", table_name="library_track")
    op.drop_table("library_track")
