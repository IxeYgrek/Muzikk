"""listening service accounts

ListenBrainz and Last.fm are personal: the handle decides whose taste the
recommendations follow, and the token decides which account a listen is
credited to. Both therefore belong to the user rather than to the install.

Revision ID: e7a1c5d93f24
Revises: d4c8e2a91b70
Create Date: 2026-09-24 18:40:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a1c5d93f24"
down_revision: str | None = "d4c8e2a91b70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("listenbrainz_user", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("listenbrainz_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("lastfm_user", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("lastfm_session_key", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("lastfm_session_key")
        batch_op.drop_column("lastfm_user")
        batch_op.drop_column("listenbrainz_token")
        batch_op.drop_column("listenbrainz_user")
