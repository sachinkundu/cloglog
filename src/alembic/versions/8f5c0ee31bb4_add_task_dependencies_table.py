"""add task_dependencies table

Revision ID: 8f5c0ee31bb4
Revises: f1a2b3c4d5e6
Create Date: 2026-04-19 10:57:46.972580

Task-level dependencies for F-11. Mirrors the shape of
``feature_dependencies``: composite PK, FK both ways, plus a CHECK
against self-loops and an index on the RHS column so cycle-detection
queries don't full-scan.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f5c0ee31bb4"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("depends_on_task_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dep_no_self_loop"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "depends_on_task_id"),
    )
    op.create_index(
        "ix_task_dependencies_depends_on_task_id",
        "task_dependencies",
        ["depends_on_task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_task_dependencies_depends_on_task_id", table_name="task_dependencies")
    op.drop_table("task_dependencies")
