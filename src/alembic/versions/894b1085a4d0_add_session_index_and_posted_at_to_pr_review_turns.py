"""add_session_index_and_posted_at_to_pr_review_turns

T-375 at-most-once posting per session: persist the cross-session counter
(``session_index``) and the post timestamp (``posted_at``) on each
``pr_review_turns`` row, plus a partial unique index that guarantees at
most one ``posted_at IS NOT NULL`` row per ``(pr_url, stage, session_index)``.

Background — bug being fixed
----------------------------

A single codex review session occasionally posted two GitHub reviews under
the same ``session N/5`` counter. The session counter is computed once at
``ReviewEngineConsumer._review_pr`` entry from ``count_bot_reviews``, and
the per-session header is the same for every turn the loop runs in that
session. With ``codex_max_turns > 1`` (or a webhook re-fire that re-enters
on the next turn), the loop's per-turn ``post_review`` call could fire
twice within one logical session — both reviews stamped ``session N/5`` —
which inflated review pressure on the contributor and made review history
ambiguous.

The columns added here let the loop record which session each turn belongs
to, and the partial unique index lets the database enforce the contract:
at most one *posted* row per ``(pr_url, stage, session_index)``. Operators
can verify the invariant with::

    SELECT pr_url, stage, session_index, COUNT(*)
    FROM pr_review_turns
    WHERE posted_at IS NOT NULL
    GROUP BY 1, 2, 3
    HAVING COUNT(*) > 1;

A non-empty result row would mean the constraint silently regressed.

Both columns are nullable so historical rows (created before this
migration) round-trip cleanly. New rows written by ``claim_turn`` carry a
non-null ``session_index``; ``posted_at`` is set by ``mark_posted`` only
after a successful GitHub POST.

Revision ID: 894b1085a4d0
Revises: 1574708abb78
Create Date: 2026-05-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "894b1085a4d0"
down_revision: str | None = "1574708abb78"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pr_review_turns",
        sa.Column("session_index", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pr_review_turns",
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial unique: only enforces at-most-one row per (pr_url, stage,
    # session_index) WHERE posted_at IS NOT NULL. Pre-T-375 rows have
    # NULL session_index and NULL posted_at; they don't participate.
    op.create_index(
        "uq_pr_review_turns_one_post_per_session",
        "pr_review_turns",
        ["pr_url", "stage", "session_index"],
        unique=True,
        postgresql_where=sa.text("posted_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_pr_review_turns_one_post_per_session",
        table_name="pr_review_turns",
    )
    op.drop_column("pr_review_turns", "posted_at")
    op.drop_column("pr_review_turns", "session_index")
