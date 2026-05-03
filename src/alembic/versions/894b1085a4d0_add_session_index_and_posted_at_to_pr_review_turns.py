"""add_session_index_and_posted_at_to_pr_review_turns

T-375 webhook-re-fire dedupe: persist the cross-session counter
(``session_index``) and the post timestamp (``posted_at``) on each
``pr_review_turns`` row, so a webhook redelivery for the same SHA can
detect "this session already posted" and short-circuit before the loop
re-POSTs under the same ``session N/5`` counter.

Background — bug being fixed
----------------------------

A webhook redelivery for the same head_sha (session_index is constant for
a given commit because ``count_bot_reviews`` collapses by ``commit_id``)
caused ``ReviewLoop.run`` to advance the turn counter and POST a SECOND
review under the same ``session N/5`` header — visible to contributors as
duplicate stamps on the PR. ``ReviewLoop`` now reads ``posted_at`` /
``session_index`` from prior turn rows on the same SHA and short-circuits
the run before claiming any new turns when this session has already
posted.

Note on scope: this migration deliberately does NOT add a database-level
partial unique on ``(pr_url, stage, session_index) WHERE posted_at IS NOT
NULL``. Existing per-turn semantics (``docs/design/two-stage-pr-review.md``
§3.3) say one POST per turn, and a session may legitimately produce
multiple POSTs when ``codex_max_turns > 1`` and later turns surface new
findings — codex's review of an earlier draft of T-375 flagged that
suppressing those later POSTs hides findings from contributors. So both
columns are informational/audit-trail only; uniqueness is enforced at
the application layer in ``ReviewLoop`` for the webhook-re-fire path
and intentionally not for the intra-run multi-turn path.

Both columns are nullable so historical rows (created before this
migration) round-trip cleanly. New rows written by ``claim_turn`` carry a
non-null ``session_index``; ``posted_at`` is set by ``mark_posted`` after
each successful GitHub POST.

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


def downgrade() -> None:
    op.drop_column("pr_review_turns", "posted_at")
    op.drop_column("pr_review_turns", "session_index")
