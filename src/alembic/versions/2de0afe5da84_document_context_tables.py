"""document_context_tables

Revision ID: 2de0afe5da84
Revises: 318e2b5f41df
Create Date: 2026-04-03 11:32:55.269633
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2de0afe5da84"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("source_path", sa.String(length=1000), nullable=False),
        sa.Column("attached_to_type", sa.String(length=50), nullable=False),
        sa.Column("attached_to_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("documents")
