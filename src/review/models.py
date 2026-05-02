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
