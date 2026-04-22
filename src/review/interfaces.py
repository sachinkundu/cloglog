"""Protocols exposed by the Review context.

Gateway's two-stage review sequencer depends on ``IReviewTurnRegistry`` —
a Protocol — and never imports the concrete repository or SQLAlchemy model.
This is the Open Host Service boundary in ``docs/ddd-context-map.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ReviewTurnSnapshot:
    """Read-only snapshot of a single persisted turn.

    Carried across the Gateway→Review boundary instead of the ORM row so
    Gateway never binds to ``src.review.models``.
    """

    project_id: UUID
    pr_url: str
    pr_number: int
    head_sha: str
    stage: str
    turn_number: int
    status: str
    finding_count: int | None
    consensus_reached: bool
    elapsed_seconds: float | None


class IReviewTurnRegistry(Protocol):
    """Persistent turn accounting for the two-stage review pipeline."""

    async def claim_turn(
        self,
        *,
        project_id: UUID,
        pr_url: str,
        pr_number: int,
        head_sha: str,
        stage: str,
        turn_number: int,
    ) -> bool:
        """Atomically insert a ``running`` turn row.

        Returns ``True`` iff this caller won the slot. ``False`` means another
        handler already claimed the same ``(pr_url, head_sha, stage, turn_number)``
        — the caller must exit without running the subprocess.

        Implementation uses ``INSERT ... ON CONFLICT DO NOTHING`` on the
        unique index ``uq_pr_review_turns_key``.
        """
        ...

    async def complete_turn(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
        status: str,
        finding_count: int | None,
        consensus_reached: bool,
        elapsed_seconds: float,
    ) -> None:
        """Mark a previously claimed turn as terminal (completed / timed_out / failed)."""
        ...

    async def latest_for(self, pr_url: str, head_sha: str) -> ReviewTurnSnapshot | None:
        """Return the most recently-created row for ``(pr_url, head_sha)``, or None.

        Used by the dashboard to render the ``opencode 2/5`` / ``codex 1/2`` badge
        (see ``docs/design/two-stage-pr-review.md`` §8.3).
        """
        ...

    async def turns_for_stage(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
    ) -> list[ReviewTurnSnapshot]:
        """Return every turn for a single (pr_url, head_sha, stage), oldest first.

        Used by the consensus checker to compute predicate (b) — zero-new-findings
        across the union of all prior turns.
        """
        ...
