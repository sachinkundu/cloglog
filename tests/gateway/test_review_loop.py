"""Pure-logic and integration tests for the T-248 ReviewLoop (no real subprocess).

The loop itself is exercised with:
  - an in-memory ``FakeRegistry`` (implements IReviewTurnRegistry on a dict)
  - a ``StubReviewer`` that returns pre-programmed (result, elapsed, timed_out)
  - ``post_review`` patched away so no HTTP calls are made

All consensus logic, turn-accounting, and status handling are verified here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.gateway.review_engine import ReviewFinding, ReviewResult
from src.gateway.review_loop import (
    OpencodeReviewer,
    ReviewLoop,
    _finding_key,
    _reached_consensus,
)
from src.review.interfaces import PriorContext, PriorTurnSummary, ReviewTurnSnapshot

# ---------------------------------------------------------------------------
# In-memory fake registry
# ---------------------------------------------------------------------------


class FakeRegistry:
    """Minimal IReviewTurnRegistry backed by a dict — no real DB."""

    def __init__(self) -> None:
        # key: (pr_url, head_sha, stage, turn_number) -> ReviewTurnSnapshot
        self._turns: dict[tuple[str, str, str, int], ReviewTurnSnapshot] = {}
        # T-367: persisted findings + learnings keyed the same way; populated
        # by record_findings_and_learnings, replayed by
        # prior_findings_and_learnings. Kept on the side instead of widening
        # ReviewTurnSnapshot so callers that only care about turn-count
        # behaviour are unaffected.
        self._findings: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
        self._learnings: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}

    async def claim_turn(
        self,
        *,
        project_id: uuid.UUID,
        pr_url: str,
        pr_number: int,
        head_sha: str,
        stage: str,
        turn_number: int,
    ) -> bool:
        key = (pr_url, head_sha, stage, turn_number)
        if key in self._turns:
            return False
        self._turns[key] = ReviewTurnSnapshot(
            project_id=project_id,
            pr_url=pr_url,
            pr_number=pr_number,
            head_sha=head_sha,
            stage=stage,
            turn_number=turn_number,
            status="running",
            finding_count=None,
            consensus_reached=False,
            elapsed_seconds=None,
        )
        return True

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
        key = (pr_url, head_sha, stage, turn_number)
        if key not in self._turns:
            return
        old = self._turns[key]
        self._turns[key] = ReviewTurnSnapshot(
            project_id=old.project_id,
            pr_url=old.pr_url,
            pr_number=old.pr_number,
            head_sha=old.head_sha,
            stage=old.stage,
            turn_number=old.turn_number,
            status=status,
            finding_count=finding_count,
            consensus_reached=consensus_reached,
            elapsed_seconds=elapsed_seconds,
        )

    async def latest_for(self, pr_url: str, head_sha: str) -> ReviewTurnSnapshot | None:
        candidates = [
            snap
            for (pu, hs, _s, _t), snap in self._turns.items()
            if pu == pr_url and hs == head_sha
        ]
        return candidates[-1] if candidates else None

    async def turns_for_stage(
        self, *, pr_url: str, head_sha: str, stage: str
    ) -> list[ReviewTurnSnapshot]:
        return [
            snap
            for (pu, hs, s, _t), snap in sorted(self._turns.items(), key=lambda x: x[0][3])
            if pu == pr_url and hs == head_sha and s == stage
        ]

    async def reset_to_running(
        self, *, pr_url: str, head_sha: str, stage: str, turn_number: int
    ) -> bool:
        key = (pr_url, head_sha, stage, turn_number)
        snap = self._turns.get(key)
        if snap is None or snap.status != "failed":
            return False
        self._turns[key] = ReviewTurnSnapshot(
            project_id=snap.project_id,
            pr_url=snap.pr_url,
            pr_number=snap.pr_number,
            head_sha=snap.head_sha,
            stage=snap.stage,
            turn_number=snap.turn_number,
            status="running",
            finding_count=None,
            consensus_reached=False,
            elapsed_seconds=None,
        )
        return True

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
        key = (pr_url, head_sha, stage, turn_number)
        self._findings[key] = list(findings_json)
        self._learnings[key] = list(learnings_json)

    async def prior_findings_and_learnings(self, *, pr_url: str, stage: str) -> PriorContext:
        # Order by (head_sha, turn_number) — tests use stable insertion shape.
        rows = sorted(
            (
                (key, snap)
                for key, snap in self._turns.items()
                if key[0] == pr_url and key[2] == stage and snap.status == "completed"
            ),
            key=lambda x: (x[0][1], x[0][3]),
        )
        turns: list[PriorTurnSummary] = []
        for key, snap in rows:
            findings = self._findings.get(key)
            if findings is None:
                continue
            turns.append(
                PriorTurnSummary(
                    head_sha=snap.head_sha,
                    turn_number=snap.turn_number,
                    findings=list(findings),
                    learnings=list(self._learnings.get(key, [])),
                )
            )
        return PriorContext(pr_url=pr_url, turns=turns)


# ---------------------------------------------------------------------------
# Stub reviewer
# ---------------------------------------------------------------------------


@dataclass
class StubReviewer:
    """Returns a pre-programmed sequence of (result, elapsed, timed_out) tuples."""

    bot_username: str = "stub-bot[bot]"
    display_label: str = "stub"
    # Each call pops from the front; last item is repeated if list exhausted.
    responses: list[tuple[ReviewResult | None, float, bool]] = field(default_factory=list)
    _call_count: int = field(default=0, init=False, repr=False)

    async def run(
        self,
        *,
        diff: str,
        pr_number: int,
        turn: int,
        max_turns: int,
        prior_context: Any = None,
        pr_body: str | None = None,
    ) -> tuple[ReviewResult | None, float, bool]:
        del prior_context, pr_body  # not exercised by these unit tests
        idx = min(self._call_count, len(self.responses) - 1)
        self._call_count += 1
        return self.responses[idx]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ID = uuid.uuid4()
_PR_URL = "https://github.com/owner/repo/pull/1"
_PR_NUMBER = 1
_REPO = "owner/repo"
_SHA = "abc123" + "0" * 34


def _make_loop(
    reviewer: Any,
    *,
    max_turns: int = 3,
    registry: FakeRegistry | None = None,
    head_sha: str = _SHA,
    stage: str = "codex",
    session_index: int = 1,
    max_sessions: int = 5,
) -> ReviewLoop:
    reg = registry or FakeRegistry()
    return ReviewLoop(
        reviewer,
        max_turns=max_turns,
        registry=reg,
        project_id=_PROJECT_ID,
        pr_url=_PR_URL,
        pr_number=_PR_NUMBER,
        repo_full_name=_REPO,
        head_sha=head_sha,
        stage=stage,
        reviewer_token="fake-token",
        session_index=session_index,
        max_sessions=max_sessions,
    )


def _ok_result(
    findings: list[ReviewFinding] | None = None,
    status: str | None = None,
    verdict: str = "comment",
) -> ReviewResult:
    # Default ``verdict="comment"`` (not "approve") so tests of the
    # findings-diff predicate aren't accidentally short-circuited by the
    # verdict-based predicate added 2026-04-23. Tests that exercise the
    # approve short-circuit pass ``verdict="approve"`` explicitly.
    return ReviewResult(
        verdict=verdict,
        summary="looks good",
        findings=findings or [],
        status=status,
    )


def _finding(file: str = "a.py", line: int = 1, title: str = "issue") -> ReviewFinding:
    return ReviewFinding(file=file, line=line, severity="medium", body="body", title=title)


# ---------------------------------------------------------------------------
# _finding_key
# ---------------------------------------------------------------------------


class TestFindingKey:
    def test_dict_form(self) -> None:
        key = _finding_key({"file": "a.py", "line": 5, "title": "  BUG  "})
        assert key == ("a.py", 5, "bug")

    def test_model_form(self) -> None:
        f = _finding(file="src/x.py", line=10, title="SQL injection")
        key = _finding_key(f)
        assert key == ("src/x.py", 10, "sql injection")

    def test_lowercases_title(self) -> None:
        key = _finding_key({"file": "f.py", "line": 1, "title": "UPPER"})
        assert key[2] == "upper"

    def test_strips_whitespace(self) -> None:
        key = _finding_key({"file": "f.py", "line": 1, "title": "  trim  "})
        assert key[2] == "trim"

    def test_missing_keys_default_to_empty(self) -> None:
        key = _finding_key({})
        assert key == ("", 0, "")


# ---------------------------------------------------------------------------
# _reached_consensus
# ---------------------------------------------------------------------------


class TestReachedConsensus:
    def test_explicit_status_short_circuits(self) -> None:
        result = _ok_result(
            findings=[_finding(file="x.py", line=1, title="new issue")],
            status="no_further_concerns",
        )
        # Has new findings, but explicit status → consensus
        assert _reached_consensus(result=result, prior_finding_keys=set()) is True

    def test_identical_findings_across_turns_returns_true(self) -> None:
        f = _finding(file="a.py", line=5, title="memory leak")
        prior = {_finding_key(f)}
        result = _ok_result(findings=[f])
        assert _reached_consensus(result=result, prior_finding_keys=prior) is True

    def test_new_finding_returns_false(self) -> None:
        prior: set[tuple[str, int, str]] = set()
        result = _ok_result(findings=[_finding(file="a.py", line=5, title="new")])
        assert _reached_consensus(result=result, prior_finding_keys=prior) is False

    def test_case_different_title_same_key_returns_true(self) -> None:
        # Prior recorded lower-cased; current has mixed-case
        prior = {("a.py", 1, "memory leak")}
        f_mixed = _finding(file="a.py", line=1, title="Memory Leak")
        result = _ok_result(findings=[f_mixed])
        assert _reached_consensus(result=result, prior_finding_keys=prior) is True

    def test_same_title_different_line_returns_false(self) -> None:
        """Same title at a different line is a new location — not consensus."""
        prior = {("a.py", 1, "bug")}
        f_diff_line = _finding(file="a.py", line=2, title="bug")
        result = _ok_result(findings=[f_diff_line])
        assert _reached_consensus(result=result, prior_finding_keys=prior) is False

    def test_empty_findings_with_no_prior_returns_true(self) -> None:
        result = _ok_result(findings=[])
        assert _reached_consensus(result=result, prior_finding_keys=set()) is True

    def test_approve_verdict_short_circuits_turn_1_with_findings(self) -> None:
        """Per user directive 2026-04-23 (T-263): ``verdict='approve'`` on
        any turn, even turn 1, is itself a short-circuit signal — the
        reviewer is done, hand off to the next stage. Findings posted this
        turn stay posted; subsequent turns are skipped.
        """
        result = _ok_result(
            findings=[_finding(file="x.py", line=1, title="nit: style")],
            verdict="approve",
        )
        assert _reached_consensus(result=result, prior_finding_keys=set()) is True

    def test_approve_verdict_short_circuits_without_status(self) -> None:
        """An approve verdict short-circuits even when ``status`` is None
        (model didn't emit the explicit consensus flag but verdict alone is enough)."""
        result = _ok_result(findings=[], status=None, verdict="approve")
        assert _reached_consensus(result=result, prior_finding_keys=set()) is True

    def test_request_changes_verdict_does_not_short_circuit_on_new_findings(self) -> None:
        """Negative case — non-approve verdict + new findings must not short-circuit."""
        result = _ok_result(
            findings=[_finding(file="a.py", line=1, title="bug")],
            verdict="request_changes",
        )
        assert _reached_consensus(result=result, prior_finding_keys=set()) is False

    def test_comment_verdict_does_not_short_circuit_on_new_findings(self) -> None:
        """Negative case — comment verdict + new findings must not short-circuit."""
        result = _ok_result(
            findings=[_finding(file="a.py", line=1, title="suggestion")],
            verdict="comment",
        )
        assert _reached_consensus(result=result, prior_finding_keys=set()) is False

    def test_approve_with_critical_finding_does_not_short_circuit(self) -> None:
        """Self-contradictory output — approve verdict + a ``critical``
        severity finding — must fall through to the empty-diff predicate
        (false on turn 1 with any finding). Observed on PR #190 2026-04-23
        with gemma4-e4b-32k. See the fix directly above this test."""
        critical = ReviewFinding(
            file="a.py", line=1, severity="critical", body="bug", title="crash"
        )
        result = _ok_result(findings=[critical], verdict="approve")
        assert _reached_consensus(result=result, prior_finding_keys=set()) is False

    def test_approve_with_high_finding_does_not_short_circuit(self) -> None:
        """``high`` severity is equally a contradiction with an approve verdict."""
        high = ReviewFinding(
            file="a.py", line=1, severity="high", body="issue", title="ddd violation"
        )
        result = _ok_result(findings=[high], verdict="approve")
        assert _reached_consensus(result=result, prior_finding_keys=set()) is False

    def test_approve_with_medium_and_info_findings_still_short_circuits(self) -> None:
        """``medium`` and ``info`` severity findings are nit-level — an
        approve verdict alongside them is the intended short-circuit case.
        Matches the user directive: ``if it says pass, it should just do one``."""
        nits = [
            ReviewFinding(file="a.py", line=1, severity="medium", body="b", title="t"),
            ReviewFinding(file="b.py", line=2, severity="info", body="b", title="t"),
        ]
        result = _ok_result(findings=nits, verdict="approve")
        assert _reached_consensus(result=result, prior_finding_keys=set()) is True


# ---------------------------------------------------------------------------
# ReviewLoop._build_body_header
# ---------------------------------------------------------------------------


class TestBuildBodyHeader:
    def test_format(self) -> None:
        """T-290: header shows cross-session counter, not intra-session turn.

        Before T-290 every webhook firing rendered ``turn 1/2`` regardless of
        which PR session it was (a new session starts from turn 1, so the
        label was identical across sessions). Now it renders
        ``session N/M`` where N is the 1-based session index and M is
        ``MAX_REVIEWS_PER_PR``.
        """
        stub = StubReviewer(display_label="codex", responses=[])
        header = ReviewLoop._build_body_header(stub, session_index=2, max_sessions=5)
        assert header == "**codex — session 2/5**"

    def test_format_with_model_suffix(self) -> None:
        """Opencode display_label carries its model suffix through unchanged."""
        stub = StubReviewer(display_label="opencode (gemma4:e4b)", responses=[])
        header = ReviewLoop._build_body_header(stub, session_index=1, max_sessions=5)
        assert header == "**opencode (gemma4:e4b) — session 1/5**"


# ---------------------------------------------------------------------------
# ReviewLoop.run — orchestration
# ---------------------------------------------------------------------------

_PATCH_POST_REVIEW = "src.gateway.review_loop.post_review"


class TestSessionHeaderInPostedBody:
    """T-290: the header prepended to each posted review must use the
    cross-session counter, not the per-session turn index. A second webhook
    firing on the same PR renders ``session 2/5``; a reader can tell it
    apart from session 1 (before T-290 both said ``turn 1/2``).
    """

    @pytest.mark.asyncio
    async def test_posted_body_uses_session_counter(self) -> None:
        stub = StubReviewer(
            display_label="codex",
            responses=[(_ok_result(status="no_further_concerns"), 1.0, False)],
        )
        registry = FakeRegistry()
        loop = _make_loop(
            stub,
            max_turns=2,
            registry=registry,
            session_index=2,
            max_sessions=5,
        )

        mock_post = AsyncMock(return_value=True)
        with patch(_PATCH_POST_REVIEW, new=mock_post):
            await loop.run(diff="some diff")

        assert mock_post.await_count == 1
        posted_result = mock_post.await_args.args[2]
        # First line of the summary is the session header — no ``turn N/M``.
        first_line = posted_result.summary.splitlines()[0]
        assert first_line == "**codex — session 2/5**"
        assert "turn " not in first_line


class TestReviewLoopRun:
    @pytest.mark.asyncio
    async def test_short_circuits_on_explicit_status(self) -> None:
        """Loop stops before cap when reviewer returns no_further_concerns."""
        stub = StubReviewer(
            responses=[
                (_ok_result(status="no_further_concerns"), 1.0, False),
            ]
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=5, registry=registry)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="some diff")

        assert outcome.turns_used == 1
        assert outcome.consensus_reached is True

    @pytest.mark.asyncio
    async def test_short_circuits_on_empty_diff_second_turn(self) -> None:
        """Turn 2 with same findings as turn 1 → empty diff → consensus."""
        f = _finding(file="b.py", line=3, title="issue")
        stub = StubReviewer(
            responses=[
                (_ok_result(findings=[f]), 1.0, False),
                (_ok_result(findings=[f]), 1.0, False),  # same key — empty diff
            ]
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=5, registry=registry)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="some diff")

        assert outcome.consensus_reached is True
        assert outcome.turns_used == 2

    @pytest.mark.asyncio
    async def test_runs_to_cap_when_no_consensus(self) -> None:
        """When every turn adds new findings, loop runs all max_turns."""

        def _unique_finding(n: int) -> ReviewFinding:
            return _finding(file="x.py", line=n, title=f"finding-{n}")

        stub = StubReviewer(
            responses=[(_ok_result(findings=[_unique_finding(i)]), 1.0, False) for i in range(1, 4)]
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=3, registry=registry)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="some diff")

        assert outcome.turns_used == 3
        assert outcome.consensus_reached is False

    @pytest.mark.asyncio
    async def test_failed_turn_marks_status_failed_and_continues(self) -> None:
        """A reviewer returning (None, elapsed, False) → failed, loop continues."""
        stub = StubReviewer(
            responses=[
                (None, 2.0, False),  # turn 1 fails
                (_ok_result(status="no_further_concerns"), 1.0, False),  # turn 2 succeeds
            ]
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=3, registry=registry)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="diff")

        # Turn 1 failed, turn 2 reached consensus
        assert "turn 1: failed" in outcome.errors
        turns = await registry.turns_for_stage(pr_url=_PR_URL, head_sha=_SHA, stage="codex")
        turn_1 = next(t for t in turns if t.turn_number == 1)
        assert turn_1.status == "failed"
        assert outcome.consensus_reached is True

    @pytest.mark.asyncio
    async def test_timed_out_turn_marks_status_timed_out(self) -> None:
        """A reviewer returning (None, elapsed, True) → timed_out status."""
        stub = StubReviewer(
            responses=[
                (None, 300.0, True),  # turn 1 times out
                (_ok_result(), 1.0, False),
            ]
        )
        registry = FakeRegistry()
        loop = _make_loop(stub, max_turns=3, registry=registry)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            await loop.run(diff="diff")

        turns = await registry.turns_for_stage(pr_url=_PR_URL, head_sha=_SHA, stage="codex")
        turn_1 = next(t for t in turns if t.turn_number == 1)
        assert turn_1.status == "timed_out"

    @pytest.mark.asyncio
    async def test_resumes_from_next_turn_on_webhook_refire(self) -> None:
        """On webhook re-fire, pre-existing turns are detected and loop starts from turn N+1."""
        sha = "refire" + "0" * 34
        registry = FakeRegistry()

        # Simulate turn 1 already completed (a prior webhook delivery ran it)
        registry._turns[(_PR_URL, sha, "codex", 1)] = ReviewTurnSnapshot(
            project_id=_PROJECT_ID,
            pr_url=_PR_URL,
            pr_number=_PR_NUMBER,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            finding_count=1,
            consensus_reached=False,
            elapsed_seconds=1.0,
        )

        stub = StubReviewer(
            responses=[
                (_ok_result(status="no_further_concerns"), 1.0, False),
            ]
        )
        loop = _make_loop(stub, max_turns=3, registry=registry, head_sha=sha)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="diff")

        # Loop should have run turn 2 (not turn 1 again), and reached consensus
        turns = await registry.turns_for_stage(pr_url=_PR_URL, head_sha=sha, stage="codex")
        turn_numbers = [t.turn_number for t in turns]
        assert 1 in turn_numbers
        assert 2 in turn_numbers
        assert outcome.consensus_reached is True

    @pytest.mark.asyncio
    async def test_claim_returns_false_stops_loop_at_concurrent_turn(self) -> None:
        """If claim_turn returns False on the *current* start turn (concurrent handler
        already claimed it while this handler is entering the for-loop), the loop
        breaks without incrementing turns_used beyond the pre-existing value.

        _compute_next_turn sees no existing rows → start_turn=1.
        The FakeRegistry is replaced with a spy that returns False on turn 1.
        """
        sha = "claimed" + "0" * 33

        class AlwaysDeniesRegistry(FakeRegistry):
            async def claim_turn(self, **kwargs: object) -> bool:  # type: ignore[override]
                return False  # concurrent handler wins every slot

            async def reset_to_running(self, **kwargs: object) -> bool:  # type: ignore[override]
                return False  # no failed row to reset either

        registry = AlwaysDeniesRegistry()
        stub = StubReviewer(responses=[(_ok_result(), 1.0, False)])
        loop = _make_loop(stub, max_turns=3, registry=registry, head_sha=sha)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="diff")

        # claim_turn returned False immediately → turns_used stays 0
        assert outcome.turns_used == 0
        assert stub._call_count == 0

    @pytest.mark.asyncio
    async def test_already_at_cap_returns_immediately(self) -> None:
        """If prior turns already reached max_turns, the loop is a no-op."""
        sha = "atcap" + "0" * 35
        registry = FakeRegistry()
        # Pre-populate turns 1..3 (max_turns=3)
        for turn in (1, 2, 3):
            registry._turns[(_PR_URL, sha, "codex", turn)] = ReviewTurnSnapshot(
                project_id=_PROJECT_ID,
                pr_url=_PR_URL,
                pr_number=_PR_NUMBER,
                head_sha=sha,
                stage="codex",
                turn_number=turn,
                status="completed",
                finding_count=0,
                consensus_reached=False,
                elapsed_seconds=1.0,
            )

        stub = StubReviewer(responses=[(_ok_result(), 1.0, False)])
        loop = _make_loop(stub, max_turns=3, registry=registry, head_sha=sha)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="diff")

        assert outcome.turns_used == 0
        assert stub._call_count == 0


# ---------------------------------------------------------------------------
# PR #187 round 1 HIGH-3 — post_review failure handling
# ---------------------------------------------------------------------------


class TestPostFailureRetryOnRefire:
    """Spec §3.3 + PR #187 round 1 HIGH-3.

    When the GitHub POST fails, the turn must be marked ``failed`` (not
    ``completed``) so a webhook re-fire can retry the same turn number via
    ``reset_to_running``. Without this fix, turn accounting advanced past the
    missing comment and the author never saw those findings.
    """

    @pytest.mark.asyncio
    async def test_post_failure_marks_turn_failed(self) -> None:
        sha = "postfail" + "0" * 32
        registry = FakeRegistry()
        stub = StubReviewer(responses=[(_ok_result(findings=[_finding()]), 1.0, False)])
        loop = _make_loop(stub, max_turns=3, registry=registry, head_sha=sha)

        # post_review returns False → GitHub rejected both attempts
        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=False)):
            outcome = await loop.run(diff="diff")

        assert outcome.turns_used == 1
        assert any("post_failed" in e for e in outcome.errors)
        # Turn row must be marked 'failed', NOT 'completed'.
        turn_rows = await registry.turns_for_stage(pr_url=_PR_URL, head_sha=sha, stage="codex")
        assert len(turn_rows) == 1
        assert turn_rows[0].status == "failed"

    @pytest.mark.asyncio
    async def test_refire_resumes_at_failed_turn(self) -> None:
        """A second webhook delivery picks up the failed turn, not max+1."""
        sha = "refire" + "0" * 34
        registry = FakeRegistry()
        # Stub that always succeeds.
        stub = StubReviewer(responses=[(_ok_result(status="no_further_concerns"), 1.0, False)])

        # First run — POST fails, turn 1 persisted as 'failed'.
        loop1 = _make_loop(stub, max_turns=3, registry=registry, head_sha=sha)
        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=False)):
            await loop1.run(diff="diff")

        # Second run — POST succeeds. Loop must pick up turn 1 again (not 2).
        stub2 = StubReviewer(responses=[(_ok_result(status="no_further_concerns"), 1.0, False)])
        loop2 = _make_loop(stub2, max_turns=3, registry=registry, head_sha=sha)
        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)) as mock_post:
            outcome = await loop2.run(diff="diff")

        # The reviewer ran one more time, posting on turn 1.
        assert stub2._call_count == 1
        mock_post.assert_awaited()
        # After success, turn 1 is completed with consensus_reached=True.
        rows = await registry.turns_for_stage(pr_url=_PR_URL, head_sha=sha, stage="codex")
        assert len(rows) == 1
        assert rows[0].status == "completed"
        assert rows[0].turn_number == 1
        assert outcome.consensus_reached is True


# ---------------------------------------------------------------------------
# PR #187 round 2 HIGH — webhook redelivery must not repost after consensus
# ---------------------------------------------------------------------------


class TestConsensusShortCircuitOnRefire:
    """Spec §3.3 + PR #187 round 2 HIGH.

    When a prior turn on the same (pr_url, head_sha, stage) already recorded
    ``consensus_reached=True``, a webhook redelivery must be a NO-OP. Without
    the short-circuit, redelivery resumed at turn N+1 and posted another
    review on a PR that was already done.
    """

    @pytest.mark.asyncio
    async def test_prior_consensus_short_circuits_whole_loop(self) -> None:
        sha = "alreadydone" + "0" * 29
        registry = FakeRegistry()
        # Pre-populate: turn 1 already completed with consensus_reached=True.
        registry._turns[(_PR_URL, sha, "codex", 1)] = ReviewTurnSnapshot(
            project_id=_PROJECT_ID,
            pr_url=_PR_URL,
            pr_number=_PR_NUMBER,
            head_sha=sha,
            stage="codex",
            turn_number=1,
            status="completed",
            finding_count=2,
            consensus_reached=True,
            elapsed_seconds=1.5,
        )

        stub = StubReviewer(responses=[(_ok_result(), 1.0, False)])
        loop = _make_loop(stub, max_turns=3, registry=registry, head_sha=sha)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)) as mock_post:
            outcome = await loop.run(diff="diff")

        # Reviewer was NOT invoked; no review posted; loop reports prior consensus.
        assert stub._call_count == 0
        mock_post.assert_not_awaited()
        assert outcome.consensus_reached is True
        assert outcome.turns_used == 1

    @pytest.mark.asyncio
    async def test_prior_consensus_on_later_turn_also_short_circuits(self) -> None:
        """Consensus on turn 2 (e.g. after 1 failed + 1 successful) still short-circuits."""
        sha = "laterconsensus" + "0" * 26
        registry = FakeRegistry()
        # Turn 1 completed without consensus, turn 2 completed WITH consensus.
        for turn, consensus in [(1, False), (2, True)]:
            registry._turns[(_PR_URL, sha, "codex", turn)] = ReviewTurnSnapshot(
                project_id=_PROJECT_ID,
                pr_url=_PR_URL,
                pr_number=_PR_NUMBER,
                head_sha=sha,
                stage="codex",
                turn_number=turn,
                status="completed",
                finding_count=1,
                consensus_reached=consensus,
                elapsed_seconds=1.0,
            )

        stub = StubReviewer(responses=[(_ok_result(), 1.0, False)])
        loop = _make_loop(stub, max_turns=3, registry=registry, head_sha=sha)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)) as mock_post:
            outcome = await loop.run(diff="diff")

        assert stub._call_count == 0
        mock_post.assert_not_awaited()
        assert outcome.consensus_reached is True
        assert outcome.turns_used == 2


# ---------------------------------------------------------------------------
# Opencode invocation + prompt pin (T-268)
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPENCODE_PROMPT_FILE = _REPO_ROOT / ".github" / "opencode" / "prompts" / "review.md"


class TestOpencodeArgv:
    """The opencode CLI argv MUST include --pure (T-272 hotfix).

    T-272 regression: removing --pure in T-268 made opencode agentic
    (tool calls via default plugins). gemma4-e4b-32k then narrates tool
    calls instead of emitting JSON and parse_reviewer_output fails.
    See PR #194 (2026-04-23 live breakage). --pure = "no plugins" =
    single-shot text emission. MUST be in the argv.
    """

    def test_opencode_argv_passes_pure(self) -> None:
        reviewer = OpencodeReviewer(_REPO_ROOT)
        args = reviewer._build_args("full prompt body")
        assert "--pure" in args
        assert "--dangerously-skip-permissions" in args


class TestOpencodePromptPin:
    """Pin the opencode prompt to the deep-verification framing (T-268 + T-272).

    T-268 flipped the prompt from "first-pass" to "deep verification review" to
    stop the pass-everything bias observed on PR #190.

    T-272 hotfix trims the T-268 rewrite's filesystem-access framing — under
    ``--pure`` the model has no tools, so claims like "FULL ACCESS to the
    project filesystem. USE IT." and "evidence from a file you read outside
    the diff" are dishonest. They must be gone; the honest "no tool access"
    analogue must be present. See PR #194 live breakage on 2026-04-23.
    """

    def _prompt(self) -> str:
        return _OPENCODE_PROMPT_FILE.read_text()

    def test_opencode_prompt_has_deep_review_framing(self) -> None:
        text = self._prompt()
        assert "deep verification review" in text
        # T-272: replaced the file-read framing with the honest "no tool
        # access" paragraph. Both the positive presence of the new phrase and
        # the absence of the old dishonest phrases are load-bearing.
        assert "no tool access" in text
        assert "do not claim to have read files outside the diff" in text

    def test_opencode_prompt_drops_dishonest_file_access_framing(self) -> None:
        # T-272: these phrases imply the model can read files outside the
        # diff. Under ``--pure`` it cannot. They must not return.
        text = self._prompt()
        assert "FULL ACCESS to the project filesystem" not in text
        assert "evidence from a file you read outside the diff" not in text

    def test_opencode_prompt_drops_first_pass_framing(self) -> None:
        text = self._prompt().lower()
        assert "first-pass" not in text
        assert "cheap checks" not in text
        assert "leave deep architectural judgement for the cloud reviewer" not in text
        # The "turn 1" pass-bias instruction must not return.
        assert "on turn 1 specifically" not in text

    def test_opencode_prompt_retains_json_schema_block(self) -> None:
        text = self._prompt()
        # The sequencer's parser depends on this exact shape.
        assert '"overall_correctness"' in text
        assert '"no_further_concerns"' in text
        assert '"review_in_progress"' in text
