"""add_pr_review_turns

Create the ``pr_review_turns`` table owned by the new Review bounded context.
Additive only — no backfill, no destructive changes to existing tables.

Spurious index drops for ``ix_notifications_project_id_read``,
``ix_task_notes_task_id``, and ``uq_tasks_close_off_worktree_id`` that
autogenerate proposed have been deleted on purpose — those are partial /
conditional indexes that SQLAlchemy autogenerate does not recognize; dropping
them here would mask real schema drift on `notifications`, `task_notes`, and
`tasks`.

Revision ID: 32bcc4c15715
Revises: d2a1b3c4e5f6
Create Date: 2026-04-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "32bcc4c15715"
down_revision: str | None = "d2a1b3c4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pr_review_turns",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("pr_url", sa.String(length=1000), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=True),
        sa.Column(
            "consensus_reached",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("elapsed_seconds", sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("stage IN ('opencode', 'codex')", name="ck_pr_review_turns_stage"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'timed_out', 'failed')",
            name="ck_pr_review_turns_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pr_url",
            "head_sha",
            "stage",
            "turn_number",
            name="uq_pr_review_turns_key",
        ),
    )
    op.create_index(
        "ix_pr_review_turns_pr",
        "pr_review_turns",
        ["pr_url", "head_sha"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_pr_review_turns_pr", table_name="pr_review_turns")
    op.drop_table("pr_review_turns")
