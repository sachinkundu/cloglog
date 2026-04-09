"""Add agent_token_hash to worktrees.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-04-09
"""

import sqlalchemy as sa

from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "worktrees",
        sa.Column("agent_token_hash", sa.String(255), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("worktrees", "agent_token_hash")
