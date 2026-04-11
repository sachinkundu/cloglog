"""add cascade delete on task_notes and notifications fk to tasks

Revision ID: 222a9f6770e5
Revises: 4cab82be967b
Create Date: 2026-04-11 08:48:51.164148
"""

from collections.abc import Sequence

from alembic import op

revision: str = "222a9f6770e5"
down_revision: str | None = "4cab82be967b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "notifications_task_id_fkey",
        "notifications",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "notifications_task_id_fkey",
        "notifications",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "task_notes_task_id_fkey",
        "task_notes",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "task_notes_task_id_fkey",
        "task_notes",
        "tasks",
        ["task_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "task_notes_task_id_fkey",
        "task_notes",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "task_notes_task_id_fkey",
        "task_notes",
        "tasks",
        ["task_id"],
        ["id"],
    )
    op.drop_constraint(
        "notifications_task_id_fkey",
        "notifications",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "notifications_task_id_fkey",
        "notifications",
        "tasks",
        ["task_id"],
        ["id"],
    )
