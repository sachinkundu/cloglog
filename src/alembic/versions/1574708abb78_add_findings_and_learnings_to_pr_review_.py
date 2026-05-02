"""add_findings_and_learnings_to_pr_review_turns

T-367 cross-push memory: persist the codex findings array + learnings array
on each ``pr_review_turns`` row so the next turn's prompt can replay them
without re-deriving. Both columns nullable so historical rows remain valid
and so opencode rows (which never carry learnings) round-trip.

Spurious index drops for ``ix_notifications_project_id_read``,
``ix_task_notes_task_id``, and ``uq_tasks_close_off_worktree_id`` that
autogenerate proposed have been deleted on purpose — those are partial /
conditional indexes that SQLAlchemy autogenerate does not recognize; dropping
them here would mask real schema drift on `notifications`, `task_notes`, and
`tasks`. Same handling as ``32bcc4c15715_add_pr_review_turns.py``.

Revision ID: 1574708abb78
Revises: a4b5c6d7e8f9
Create Date: 2026-05-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1574708abb78"
down_revision: str | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pr_review_turns",
        sa.Column("findings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "pr_review_turns",
        sa.Column("learnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pr_review_turns", "learnings_json")
    op.drop_column("pr_review_turns", "findings_json")
