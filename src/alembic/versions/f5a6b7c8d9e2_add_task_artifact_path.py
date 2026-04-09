"""add artifact_path to tasks

Revision ID: f5a6b7c8d9e2
Revises: a68cf6465fc3
Create Date: 2026-04-09
"""

import sqlalchemy as sa

from alembic import op

revision = "f5a6b7c8d9e2"
down_revision = "a68cf6465fc3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("artifact_path", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "artifact_path")
