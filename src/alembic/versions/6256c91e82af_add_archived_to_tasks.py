"""add_archived_to_tasks

Revision ID: 6256c91e82af
Revises: b5f21e047857
Create Date: 2026-04-04 14:45:30.736184
"""

import sqlalchemy as sa

from alembic import op

revision: str = "6256c91e82af"
down_revision: str | None = "b5f21e047857"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "archived")
