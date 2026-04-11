"""add_retired_to_tasks

Revision ID: 4cab82be967b
Revises: f5a6b7c8d9e2
Create Date: 2026-04-10 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4cab82be967b"
down_revision: str | None = "f5a6b7c8d9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("retired", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "retired")
