"""Database queries for the Review bounded context."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from src.review.interfaces import PriorContext, PriorTurnSummary, ReviewTurnSnapshot
from src.review.models import PrReviewTurn, PrReviewTurnStatus


class ReviewTurnRepository:
    """SQLAlchemy-backed ``IReviewTurnRegistry`` implementation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_snapshot(row: PrReviewTurn) -> ReviewTurnSnapshot:
        return ReviewTurnSnapshot(
            project_id=row.project_id,
            pr_url=row.pr_url,
            pr_number=row.pr_number,
            head_sha=row.head_sha,
            stage=row.stage,
            turn_number=row.turn_number,
            status=row.status,
            finding_count=row.finding_count,
            consensus_reached=row.consensus_reached,
            elapsed_seconds=float(row.elapsed_seconds) if row.elapsed_seconds is not None else None,
            session_index=row.session_index,
            posted_at=row.posted_at,
            outcome=row.outcome,
        )

    async def claim_turn(
        self,
        *,
        project_id: UUID,
        pr_url: str,
        pr_number: int,
        head_sha: str,
        stage: str,
        turn_number: int,
        session_index: int | None = None,
    ) -> bool:
        stmt = (
            pg_insert(PrReviewTurn)
            .values(
                project_id=project_id,
                pr_url=pr_url,
                pr_number=pr_number,
                head_sha=head_sha,
                stage=stage,
                turn_number=turn_number,
                status=PrReviewTurnStatus.RUNNING.value,
                consensus_reached=False,
                session_index=session_index,
            )
            .on_conflict_do_nothing(index_elements=["pr_url", "head_sha", "stage", "turn_number"])
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        # ``rowcount`` is provided by SQLAlchemy's ``CursorResult`` for INSERT
        # statements but the static type is the narrower ``Result``. Cast via
        # ``getattr`` so mypy doesn't trip while keeping runtime behaviour.
        rowcount = getattr(result, "rowcount", 0) or 0
        return rowcount > 0

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
        stmt = select(PrReviewTurn).where(
            PrReviewTurn.pr_url == pr_url,
            PrReviewTurn.head_sha == head_sha,
            PrReviewTurn.stage == stage,
            PrReviewTurn.turn_number == turn_number,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return
        row.status = status
        row.finding_count = finding_count
        row.consensus_reached = consensus_reached
        row.elapsed_seconds = elapsed_seconds
        row.completed_at = datetime.now(UTC)
        await self._session.commit()

    async def latest_for(self, pr_url: str, head_sha: str) -> ReviewTurnSnapshot | None:
        stmt = (
            select(PrReviewTurn)
            .where(PrReviewTurn.pr_url == pr_url, PrReviewTurn.head_sha == head_sha)
            .order_by(PrReviewTurn.created_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_snapshot(row) if row is not None else None

    async def turns_for_stage(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
    ) -> list[ReviewTurnSnapshot]:
        stmt = (
            select(PrReviewTurn)
            .where(
                PrReviewTurn.pr_url == pr_url,
                PrReviewTurn.head_sha == head_sha,
                PrReviewTurn.stage == stage,
            )
            .order_by(PrReviewTurn.created_at.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_snapshot(row) for row in rows]

    async def mark_posted(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
    ) -> bool:
        """Set ``posted_at = now()`` on a turn row.

        Returns ``True`` iff the matched row had a NULL ``posted_at`` and
        was updated. A second call on a row that already carries
        ``posted_at`` returns ``False`` (no-op) — webhook re-fire
        idempotency. There is no database-level uniqueness across rows;
        multiple turns within a single run may each call this and each
        will succeed (per-turn POST contract,
        ``docs/design/two-stage-pr-review.md`` §3.3).
        """
        stmt = (
            update(PrReviewTurn)
            .where(
                PrReviewTurn.pr_url == pr_url,
                PrReviewTurn.head_sha == head_sha,
                PrReviewTurn.stage == stage,
                PrReviewTurn.turn_number == turn_number,
                PrReviewTurn.posted_at.is_(None),
            )
            .values(posted_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        rowcount = getattr(result, "rowcount", 0) or 0
        return rowcount > 0

    async def reset_to_running(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
    ) -> bool:
        stmt = (
            update(PrReviewTurn)
            .where(
                PrReviewTurn.pr_url == pr_url,
                PrReviewTurn.head_sha == head_sha,
                PrReviewTurn.stage == stage,
                PrReviewTurn.turn_number == turn_number,
                PrReviewTurn.status == PrReviewTurnStatus.FAILED.value,
            )
            .values(
                status=PrReviewTurnStatus.RUNNING.value,
                finding_count=None,
                consensus_reached=False,
                elapsed_seconds=None,
                completed_at=None,
            )
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        rowcount = getattr(result, "rowcount", 0) or 0
        return rowcount > 0

    async def record_findings_and_learnings(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
        findings_json: list[dict[str, Any]],
        learnings_json: list[dict[str, Any]],
    ) -> None:
        stmt = (
            update(PrReviewTurn)
            .where(
                PrReviewTurn.pr_url == pr_url,
                PrReviewTurn.head_sha == head_sha,
                PrReviewTurn.stage == stage,
                PrReviewTurn.turn_number == turn_number,
            )
            .values(findings_json=findings_json, learnings_json=learnings_json)
        )
        try:
            await self._session.execute(stmt)
            await self._session.commit()
        except DBAPIError:
            # Roll back the failed transaction so the session is reusable for
            # a follow-up set_outcome call. T-407.
            await self._session.rollback()
            raise

    async def set_outcome(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
        outcome: str,
    ) -> None:
        """Stamp an outcome marker; called best-effort after a persistence failure."""
        stmt = (
            update(PrReviewTurn)
            .where(
                PrReviewTurn.pr_url == pr_url,
                PrReviewTurn.head_sha == head_sha,
                PrReviewTurn.stage == stage,
                PrReviewTurn.turn_number == turn_number,
            )
            .values(outcome=outcome)
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def prior_findings_and_learnings(
        self,
        *,
        pr_url: str,
        stage: str,
    ) -> PriorContext:
        stmt = (
            select(PrReviewTurn)
            .where(
                PrReviewTurn.pr_url == pr_url,
                PrReviewTurn.stage == stage,
                PrReviewTurn.status == PrReviewTurnStatus.COMPLETED.value,
                PrReviewTurn.findings_json.is_not(None),
            )
            .order_by(PrReviewTurn.created_at.asc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        turns = [
            PriorTurnSummary(
                head_sha=row.head_sha,
                turn_number=row.turn_number,
                findings=list(row.findings_json or []),
                learnings=list(row.learnings_json or []),
            )
            for row in rows
        ]
        return PriorContext(pr_url=pr_url, turns=turns)

    async def count_posted_codex_sessions(self, *, pr_url: str) -> int:
        """Distinct ``session_index`` over posted codex turns. T-376."""
        stmt = (
            select(PrReviewTurn.session_index)
            .where(
                PrReviewTurn.pr_url == pr_url,
                PrReviewTurn.stage == "codex",
                PrReviewTurn.posted_at.is_not(None),
                PrReviewTurn.session_index.is_not(None),
            )
            .distinct()
        )
        result = await self._session.execute(stmt)
        return len(result.scalars().all())

    async def codex_touched_pr_urls(self, *, project_id: UUID, pr_urls: list[str]) -> set[str]:
        if not pr_urls:
            return set()
        stmt = (
            select(PrReviewTurn.pr_url)
            .where(
                PrReviewTurn.project_id == project_id,
                PrReviewTurn.stage == "codex",
                PrReviewTurn.pr_url.in_(pr_urls),
            )
            .distinct()
        )
        result = await self._session.execute(stmt)
        return set(result.scalars().all())
