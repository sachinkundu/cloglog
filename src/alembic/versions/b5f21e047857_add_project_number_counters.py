"""add_project_number_counters

Revision ID: b5f21e047857
Revises: 11d3e808a91d
Create Date: 2026-04-04 13:37:48.504476
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5f21e047857"
down_revision: str | None = "11d3e808a91d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("next_epic_num", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "projects",
        sa.Column("next_feature_num", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "projects",
        sa.Column("next_task_num", sa.Integer(), nullable=False, server_default="1"),
    )

    # Backfill: set counters to max(number) + 1 for each project
    conn = op.get_bind()
    projects = conn.execute(sa.text("SELECT id FROM projects")).fetchall()
    for (project_id,) in projects:
        max_epic = conn.execute(
            sa.text("SELECT COALESCE(MAX(number), 0) FROM epics WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar_one()
        max_feature = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(f.number), 0) FROM features f "
                "JOIN epics e ON f.epic_id = e.id WHERE e.project_id = :pid"
            ),
            {"pid": project_id},
        ).scalar_one()
        max_task = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(t.number), 0) FROM tasks t "
                "JOIN features f ON t.feature_id = f.id "
                "JOIN epics e ON f.epic_id = e.id WHERE e.project_id = :pid"
            ),
            {"pid": project_id},
        ).scalar_one()
        conn.execute(
            sa.text(
                "UPDATE projects SET next_epic_num = :en, "
                "next_feature_num = :fn, next_task_num = :tn "
                "WHERE id = :pid"
            ),
            {"en": max_epic + 1, "fn": max_feature + 1, "tn": max_task + 1, "pid": project_id},
        )


def downgrade() -> None:
    op.drop_column("projects", "next_task_num")
    op.drop_column("projects", "next_feature_num")
    op.drop_column("projects", "next_epic_num")
