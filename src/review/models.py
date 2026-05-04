"""SQLAlchemy models for the Review bounded context."""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import Base


class PrReviewTurnStage(StrEnum):
    OPENCODE = "opencode"
    CODEX = "codex"


class PrReviewTurnStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class PrReviewTurn(Base):
    """One turn of one stage of a two-stage PR review.

    Keyed by ``(pr_url, head_sha, stage, turn_number)`` so that webhook re-fires
    for the same commit SHA cannot double-count turns (see
    ``docs/design/two-stage-pr-review.md`` §3.3 idempotency).
    """

    __tablename__ = "pr_review_turns"

    id: Mapped[_uuid.UUID] = mapped_column(
        primary_key=True, default=_uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[_uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    pr_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    finding_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consensus_reached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    # T-367 cross-push memory: persist the codex findings array + learnings array
    # so the next turn's prompt can replay them without re-deriving. Both nullable
    # because (a) historical rows pre-date this column, and (b) opencode rows
    # never carry learnings (the learnings field is codex-only).
    findings_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    learnings_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # T-375 webhook-re-fire dedupe: ``session_index`` records the
    # cross-session counter for the run that claimed this turn, and
    # ``posted_at`` is set when ``post_review`` returned True. ReviewLoop
    # reads these on a webhook redelivery to short-circuit before
    # re-POSTing under the same ``session N/5`` counter. No DB-level
    # uniqueness — the intra-run per-turn POST contract still applies (a
    # session legitimately produces multiple posted rows when
    # ``codex_max_turns > 1`` surfaces new findings on later turns; see
    # migration 894b1085a4d0 for rationale). Both columns nullable so
    # pre-T-375 historical rows remain valid.
    session_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # T-407: persistence-error marker. Set to 'db_error' when record_findings_and_learnings
    # fails with a DBAPIError. T-409 reads this to render a failed-persistence badge.
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("now()"),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "pr_url", "head_sha", "stage", "turn_number", name="uq_pr_review_turns_key"
        ),
        CheckConstraint("stage IN ('opencode', 'codex')", name="ck_pr_review_turns_stage"),
        CheckConstraint(
            "status IN ('running', 'completed', 'timed_out', 'failed')",
            name="ck_pr_review_turns_status",
        ),
        Index("ix_pr_review_turns_pr", "pr_url", "head_sha"),
    )
