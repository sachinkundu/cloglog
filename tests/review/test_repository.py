"""Real-DB tests for ReviewTurnRepository (T-248).

Uses the ``db_session`` fixture from ``tests/conftest.py`` — real PostgreSQL,
no mocked queries.  Each test is independent: unique (pr_url, head_sha) values
prevent UniqueConstraint conflicts between test functions.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Project
from src.review.models import PrReviewTurnStatus
from src.review.repository import ReviewTurnRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_pr(suffix: str = "") -> tuple[str, str]:
    """Return a fresh (pr_url, head_sha) pair that won't collide with other tests."""
    uid = uuid.uuid4().hex[:10]
    key = f"{uid}{suffix}"
    return f"https://github.com/owner/repo/pull/{key}", key[:40].ljust(40, "0")


async def _make_project(db_session: AsyncSession) -> Project:
    project = Project(name=f"review-repo-test-{uuid.uuid4().hex[:8]}")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# ---------------------------------------------------------------------------
# claim_turn
# ---------------------------------------------------------------------------


class TestClaimTurn:
    async def test_first_claim_returns_true(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("first")

        result = await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=1,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )

        assert result is True

    async def test_duplicate_claim_returns_false(self, db_session: AsyncSession) -> None:
        """Second claim with same key → False (idempotency §3.3)."""
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("dup")

        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=2,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )
        second = await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=2,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )

        assert second is False

    async def test_different_turn_number_claims_independently(
        self, db_session: AsyncSession
    ) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("turns")

        t1 = await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=3,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )
        t2 = await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=3,
            head_sha=head_sha,
            stage="codex",
            turn_number=2,
        )

        assert t1 is True
        assert t2 is True

    async def test_different_stage_claims_independently(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("stages")

        codex = await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=4,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )
        opencode = await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=4,
            head_sha=head_sha,
            stage="opencode",
            turn_number=1,
        )

        assert codex is True
        assert opencode is True

    async def test_new_head_sha_claims_fresh_turn1(self, db_session: AsyncSession) -> None:
        """After a completed session on sha_a, a push to sha_b starts fresh (§3.4 reset)."""
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, sha_a = _unique_pr("reset_a")
        sha_b = "b" + sha_a[1:]

        # Claim and complete a turn on sha_a
        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=5,
            head_sha=sha_a,
            stage="codex",
            turn_number=1,
        )
        await repo.complete_turn(
            pr_url=pr_url,
            head_sha=sha_a,
            stage="codex",
            turn_number=1,
            status="completed",
            finding_count=0,
            consensus_reached=True,
            elapsed_seconds=1.0,
        )

        # Fresh claim on sha_b turn 1 must succeed
        result = await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=5,
            head_sha=sha_b,
            stage="codex",
            turn_number=1,
        )

        assert result is True


# ---------------------------------------------------------------------------
# complete_turn
# ---------------------------------------------------------------------------


class TestCompleteTurn:
    async def test_updates_all_terminal_fields(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("complete")

        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=10,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )
        await repo.complete_turn(
            pr_url=pr_url,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
            status="completed",
            finding_count=3,
            consensus_reached=True,
            elapsed_seconds=12.5,
        )

        snapshot = await repo.latest_for(pr_url, head_sha)
        assert snapshot is not None
        assert snapshot.status == "completed"
        assert snapshot.finding_count == 3
        assert snapshot.consensus_reached is True
        assert snapshot.elapsed_seconds is not None
        assert abs(snapshot.elapsed_seconds - 12.5) < 0.01

    async def test_complete_with_timed_out_status(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("timeout")

        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=11,
            head_sha=head_sha,
            stage="opencode",
            turn_number=1,
        )
        await repo.complete_turn(
            pr_url=pr_url,
            head_sha=head_sha,
            stage="opencode",
            turn_number=1,
            status=PrReviewTurnStatus.TIMED_OUT.value,
            finding_count=None,
            consensus_reached=False,
            elapsed_seconds=300.0,
        )

        snapshot = await repo.latest_for(pr_url, head_sha)
        assert snapshot is not None
        assert snapshot.status == "timed_out"
        assert snapshot.finding_count is None

    async def test_complete_noop_when_row_missing(self, db_session: AsyncSession) -> None:
        """complete_turn on a non-existent row must not raise."""
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("missing")
        # No exception expected
        await repo.complete_turn(
            pr_url=pr_url,
            head_sha=head_sha,
            stage="codex",
            turn_number=99,
            status="completed",
            finding_count=0,
            consensus_reached=False,
            elapsed_seconds=1.0,
        )


# ---------------------------------------------------------------------------
# latest_for
# ---------------------------------------------------------------------------


class TestLatestFor:
    async def test_returns_none_when_no_rows(self, db_session: AsyncSession) -> None:
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("norows")
        result = await repo.latest_for(pr_url, head_sha)
        assert result is None

    async def test_returns_most_recently_created_row(self, db_session: AsyncSession) -> None:
        """latest_for returns the row with the highest turn_number (last inserted)."""
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("latest")

        # Claim two turns — they're inserted in order so turn 2 is newer
        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=20,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )
        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=20,
            head_sha=head_sha,
            stage="codex",
            turn_number=2,
        )

        latest = await repo.latest_for(pr_url, head_sha)
        assert latest is not None
        assert latest.turn_number == 2

    async def test_does_not_cross_contaminate_prs(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url_a, sha_a = _unique_pr("isolA")
        pr_url_b, sha_b = _unique_pr("isolB")

        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url_a,
            pr_number=30,
            head_sha=sha_a,
            stage="codex",
            turn_number=1,
        )

        result = await repo.latest_for(pr_url_b, sha_b)
        assert result is None


# ---------------------------------------------------------------------------
# turns_for_stage
# ---------------------------------------------------------------------------


class TestTurnsForStage:
    async def test_returns_oldest_first(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("order")

        for turn in (1, 2, 3):
            await repo.claim_turn(
                project_id=project.id,
                pr_url=pr_url,
                pr_number=40,
                head_sha=head_sha,
                stage="codex",
                turn_number=turn,
            )

        turns = await repo.turns_for_stage(pr_url=pr_url, head_sha=head_sha, stage="codex")
        assert [t.turn_number for t in turns] == [1, 2, 3]

    async def test_filters_by_stage(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("stagefilter")

        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=41,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )
        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=41,
            head_sha=head_sha,
            stage="opencode",
            turn_number=1,
        )

        codex_turns = await repo.turns_for_stage(pr_url=pr_url, head_sha=head_sha, stage="codex")
        opencode_turns = await repo.turns_for_stage(
            pr_url=pr_url, head_sha=head_sha, stage="opencode"
        )
        assert len(codex_turns) == 1
        assert all(t.stage == "codex" for t in codex_turns)
        assert len(opencode_turns) == 1
        assert all(t.stage == "opencode" for t in opencode_turns)

    async def test_returns_empty_when_no_rows(self, db_session: AsyncSession) -> None:
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("empty_stage")
        turns = await repo.turns_for_stage(pr_url=pr_url, head_sha=head_sha, stage="codex")
        assert turns == []


# ---------------------------------------------------------------------------
# FK cascade on project delete
# ---------------------------------------------------------------------------


class TestProjectFkCascade:
    async def test_turn_rows_deleted_when_project_deleted(self, db_session: AsyncSession) -> None:
        project = await _make_project(db_session)
        repo = ReviewTurnRepository(db_session)
        pr_url, head_sha = _unique_pr("cascade")

        await repo.claim_turn(
            project_id=project.id,
            pr_url=pr_url,
            pr_number=99,
            head_sha=head_sha,
            stage="codex",
            turn_number=1,
        )

        # Delete the project — cascade should remove the turn row
        await db_session.delete(project)
        await db_session.commit()

        # After delete, latest_for should find nothing
        result = await repo.latest_for(pr_url, head_sha)
        assert result is None
