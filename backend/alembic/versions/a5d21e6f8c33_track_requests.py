"""per-track requests

A request can now ask for one track rather than the album holding it. It still
names its release group, because the file is tagged and filed as part of that
record; the recording says which track of it is wanted.

Granted per account and off by default: a library filled a track at a time is a
library of partial albums.

Revision ID: a5d21e6f8c33
Revises: f3b8d1c470a9
Create Date: 2026-09-25 15:10:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5d21e6f8c33"
down_revision: str | None = "f3b8d1c470a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("request", schema=None) as batch_op:
        # Existing rows are album requests, which is what the default says.
        batch_op.add_column(
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="album")
        )
        batch_op.add_column(sa.Column("recording_mbid", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("track_title", sa.String(length=500), nullable=True))
        batch_op.create_index("ix_request_kind", ["kind"])
        batch_op.create_index("ix_request_recording_mbid", ["recording_mbid"])

    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "can_request_track", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("can_request_track")

    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_index("ix_request_recording_mbid")
        batch_op.drop_index("ix_request_kind")
        batch_op.drop_column("track_title")
        batch_op.drop_column("recording_mbid")
        batch_op.drop_column("kind")
