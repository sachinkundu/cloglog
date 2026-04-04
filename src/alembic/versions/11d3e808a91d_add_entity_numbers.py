"""add_entity_numbers

Revision ID: 11d3e808a91d
Revises: 36a1eeb6127a
Create Date: 2026-04-04 12:54:15.079739
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "11d3e808a91d"
down_revision: str | None = "36a1eeb6127a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("epics", sa.Column("number", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("features", sa.Column("number", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("number", sa.Integer(), nullable=False, server_default="0"))

    conn = op.get_bind()
    projects = conn.execute(sa.text("SELECT DISTINCT project_id FROM epics")).fetchall()
    for (project_id,) in projects:
        epics = conn.execute(
            sa.text("SELECT id FROM epics WHERE project_id = :pid ORDER BY created_at"),
            {"pid": project_id},
        ).fetchall()
        for i, (epic_id,) in enumerate(epics, 1):
            conn.execute(
                sa.text("UPDATE epics SET number = :num WHERE id = :id"),
                {"num": i, "id": epic_id},
            )

        features = conn.execute(
            sa.text(
                "SELECT f.id FROM features f"
                " JOIN epics e ON f.epic_id = e.id"
                " WHERE e.project_id = :pid ORDER BY f.created_at"
            ),
            {"pid": project_id},
        ).fetchall()
        for i, (feat_id,) in enumerate(features, 1):
            conn.execute(
                sa.text("UPDATE features SET number = :num WHERE id = :id"),
                {"num": i, "id": feat_id},
            )

        tasks = conn.execute(
            sa.text(
                "SELECT t.id FROM tasks t"
                " JOIN features f ON t.feature_id = f.id"
                " JOIN epics e ON f.epic_id = e.id"
                " WHERE e.project_id = :pid ORDER BY t.created_at"
            ),
            {"pid": project_id},
        ).fetchall()
        for i, (task_id,) in enumerate(tasks, 1):
            conn.execute(
                sa.text("UPDATE tasks SET number = :num WHERE id = :id"),
                {"num": i, "id": task_id},
            )


def downgrade() -> None:
    op.drop_column("tasks", "number")
    op.drop_column("features", "number")
    op.drop_column("epics", "number")
