"""Database queries for the Review bounded context."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.review.interfaces import ReviewTurnSnapshot
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
