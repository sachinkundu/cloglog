"""add task_notes table

Revision ID: a7b8c9d0e1f2
Revises: 6256c91e82af
Create Date: 2026-04-05
"""

import sqlalchemy as sa

from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "6256c91e82af"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_notes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_notes_task_id", "task_notes", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_task_notes_task_id")
    op.drop_table("task_notes")
