"""add role to worktrees

Adds ``worktrees.role`` (``main`` | ``worktree``) so the webhook resolver
can route unmatched PRs to the project's main-agent worktree without
depending on the path-convention-based ``settings.main_agent_inbox_path``
config (T-245).

Backfill: rows whose ``worktree_path`` does NOT contain
``/.claude/worktrees/`` get ``role='main'``; everything else stays
``'worktree'`` (the server default).

Revision ID: a3f1d2c4b5e7
Revises: 32bcc4c15715
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f1d2c4b5e7"
down_revision: str | None = "32bcc4c15715"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "worktrees",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="worktree",
        ),
    )
    # Backfill: any worktree whose path is the repo root (i.e. not under
    # a `/.claude/worktrees/` subdirectory) is the project's main agent.
    op.execute(
        "UPDATE worktrees SET role = 'main' WHERE worktree_path NOT LIKE '%/.claude/worktrees/%'"
    )


def downgrade() -> None:
    op.drop_column("worktrees", "role")
