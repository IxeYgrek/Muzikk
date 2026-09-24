"""stored recommendations

Suggestions take dozens of calls across two listening services and MusicBrainz
to build, which is far too slow to do while a page is loading. A background job
writes them here per listener, and the Discover page reads them.

Revision ID: f3b8d1c470a9
Revises: e7a1c5d93f24
Create Date: 2026-09-24 23:15:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d1c470a9"
down_revision: str | None = "e7a1c5d93f24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("release_group_mbid", sa.String(length=64), nullable=True),
        sa.Column("artist_mbid", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("artist_name", sa.String(length=500), nullable=False),
        sa.Column("seed_name", sa.String(length=500), nullable=False),
        sa.Column("seed_mbid", sa.String(length=64), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("ignored", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendation_user_id", "recommendation", ["user_id"])
    op.create_index(
        "ix_recommendation_release_group_mbid", "recommendation", ["release_group_mbid"]
    )
    op.create_index("ix_recommendation_artist_mbid", "recommendation", ["artist_mbid"])
    op.create_index(
        "ix_recommendation_user_section", "recommendation", ["user_id", "section", "kind"]
    )

    op.create_table(
        "recommendation_run",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("recommendation_run")
    op.drop_index("ix_recommendation_user_section", table_name="recommendation")
    op.drop_index("ix_recommendation_artist_mbid", table_name="recommendation")
    op.drop_index("ix_recommendation_release_group_mbid", table_name="recommendation")
    op.drop_index("ix_recommendation_user_id", table_name="recommendation")
    op.drop_table("recommendation")
