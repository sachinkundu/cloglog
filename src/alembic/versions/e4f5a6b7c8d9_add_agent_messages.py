"""add agent_messages table

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-04-08
"""

import sqlalchemy as sa

from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("worktree_id", sa.Uuid(), sa.ForeignKey("worktrees.id"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sender", sa.String(100), nullable=False, server_default="system"),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_messages_pending", "agent_messages", ["worktree_id", "delivered"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_pending")
    op.drop_table("agent_messages")
