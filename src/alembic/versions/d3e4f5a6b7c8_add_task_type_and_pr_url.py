"""add task_type and pr_url to tasks

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-04-06
"""

import sqlalchemy as sa

from alembic import op

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("task_type", sa.String(20), server_default="task", nullable=False),
    )
    op.add_column("tasks", sa.Column("pr_url", sa.String(500), nullable=True))

    # Backfill task_type based on title patterns
    op.execute("""
        UPDATE tasks SET task_type = 'spec'
        WHERE lower(title) LIKE '%design spec%'
        OR lower(title) LIKE '%write spec%'
    """)
    op.execute("""
        UPDATE tasks SET task_type = 'plan'
        WHERE lower(title) LIKE '%implementation plan%'
        OR lower(title) LIKE '%write plan%'
        OR lower(title) LIKE '%impl plan%'
    """)
    op.execute("""
        UPDATE tasks SET task_type = 'impl'
        WHERE lower(title) LIKE 'implement %'
        AND task_type = 'task'
    """)


def downgrade() -> None:
    op.drop_column("tasks", "pr_url")
    op.drop_column("tasks", "task_type")
