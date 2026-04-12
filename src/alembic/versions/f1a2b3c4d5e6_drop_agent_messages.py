"""drop agent_messages table

Messages are now delivered via Monitor + file append instead of
heartbeat piggyback. The agent_messages table is no longer needed.

Revision ID: f1a2b3c4d5e6
Revises: 8a9b0c1d2e3f
Create Date: 2026-04-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "222a9f6770e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_agent_messages_pending", table_name="agent_messages")
    op.drop_table("agent_messages")


def downgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("worktree_id", sa.UUID(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sender", sa.String(100), nullable=False, server_default="system"),
        sa.Column("delivered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["worktree_id"], ["worktrees.id"]),
    )
    op.create_index("ix_agent_messages_pending", "agent_messages", ["worktree_id", "delivered"])
