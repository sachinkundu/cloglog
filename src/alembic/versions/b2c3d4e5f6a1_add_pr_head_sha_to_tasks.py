"""Add pr_head_sha to tasks for codex status projection.

T-409: Board needs the current PR head SHA to derive codex status
(working / stale / pass / exhausted). Stored here and updated by the
webhook consumer on PR_SYNCHRONIZE / PR_OPENED events so the board
projection never calls GitHub at render time.

Revision ID: b2c3d4e5f6a1
Revises: 894b1085a4d0
Create Date: 2026-05-04
"""

import sqlalchemy as sa

from alembic import op

revision = "b2c3d4e5f6a1"
down_revision = "894b1085a4d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("pr_head_sha", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "pr_head_sha")
