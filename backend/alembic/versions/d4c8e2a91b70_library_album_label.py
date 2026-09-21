"""library album label

The library grid can filter by record label once the index stores it.
Jellyfin fills it from Studios; a local scan reads the LABEL / TPUB tag.

Revision ID: d4c8e2a91b70
Revises: b9e3f17c60a4
Create Date: 2026-09-21 10:50:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4c8e2a91b70"
down_revision: str | None = "b9e3f17c60a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("library_album", schema=None) as batch_op:
        batch_op.add_column(sa.Column("label", sa.String(length=255), nullable=True))
        batch_op.create_index("ix_library_album_label", ["label"])


def downgrade() -> None:
    with op.batch_alter_table("library_album", schema=None) as batch_op:
        batch_op.drop_index("ix_library_album_label")
        batch_op.drop_column("label")
