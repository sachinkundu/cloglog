"""add outcome to pr_review_turns

Revision ID: 479ae109c254
Revises: 894b1085a4d0
Create Date: 2026-05-04

T-407: persistence-error marker. Set to 'db_error' when
record_findings_and_learnings fails with a DBAPIError. T-409 reads this
to render a failed-persistence badge on the Kanban board.
"""

import sqlalchemy as sa

from alembic import op

revision = "479ae109c254"
down_revision = "894b1085a4d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pr_review_turns",
        sa.Column("outcome", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pr_review_turns", "outcome")
