"""add model to tasks

Revision ID: a4b5c6d7e8f9
Revises: a3f1d2c4b5e7
Create Date: 2026-04-27
"""

import sqlalchemy as sa

from alembic import op

revision = "a4b5c6d7e8f9"
down_revision = "a3f1d2c4b5e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("model", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "model")
