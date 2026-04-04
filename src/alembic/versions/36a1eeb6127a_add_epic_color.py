"""add_epic_color

Revision ID: 36a1eeb6127a
Revises: 2de0afe5da84
Create Date: 2026-04-04 11:20:20.939908
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "36a1eeb6127a"
down_revision: str | None = "2de0afe5da84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "epics",
        sa.Column("color", sa.String(length=7), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("epics", "color")
