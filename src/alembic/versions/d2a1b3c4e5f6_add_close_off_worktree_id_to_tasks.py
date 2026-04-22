"""add close_off_worktree_id to tasks

Introduces a nullable ``close_off_worktree_id`` column on ``tasks`` with a
unique constraint and an ON DELETE SET NULL FK to ``worktrees.id``.

T-246 — each worktree creation auto-files a board task tracking its
teardown. The column both (a) makes the lookup "is there already a
close-off task for this worktree?" cheap and idempotent and (b) preserves
traceability after the worktree itself is deleted: the task stays, its
``close_off_worktree_id`` is silently cleared, and it lingers on the
backlog as a flag. Postgres treats NULL as distinct for UNIQUE, so a
single unique index covers both "at most one live close-off task per
worktree" and "unlimited cleared/legacy rows."

Additive-only: never downgrades live environment state (per CLAUDE.md
"Don't rely on transient filesystem probes to drive destructive state
changes").

Revision ID: d2a1b3c4e5f6
Revises: c7d9e0f1a2b3
Create Date: 2026-04-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d2a1b3c4e5f6"
down_revision = "c7d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("close_off_worktree_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_close_off_worktree_id",
        "tasks",
        "worktrees",
        ["close_off_worktree_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_tasks_close_off_worktree_id",
        "tasks",
        ["close_off_worktree_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_close_off_worktree_id", table_name="tasks")
    op.drop_constraint("fk_tasks_close_off_worktree_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "close_off_worktree_id")
