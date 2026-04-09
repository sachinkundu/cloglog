"""add pr_merged to tasks

Revision ID: a68cf6465fc3
Revises: f5a6b7c8d9e0
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
<<<<<<<< HEAD:src/alembic/versions/a68cf6465fc3_add_pr_merged_to_tasks.py
revision: str = "a68cf6465fc3"
========
revision: str = "f5a6b7c8d9e1"
>>>>>>>> c3a3ed7 (feat: add report_artifact MCP tool and fix migration chain):src/alembic/versions/f5a6b7c8d9e1_add_pr_merged_to_tasks.py
down_revision: str = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("pr_merged", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "pr_merged")
