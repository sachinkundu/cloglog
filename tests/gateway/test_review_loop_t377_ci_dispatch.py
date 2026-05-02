"""T-377: codex finalization → CI dispatch hook.

Pins the firing rule for ``ReviewLoop._ci_dispatcher``: the hook is invoked
exactly once per (pr_url, head_sha) when the codex stage reaches a terminal
state, and never on opencode, never on early-break paths that webhook
re-fires would resume, and never on a re-fired-already-finalized run.

Tested behaviours (acceptance from task.md):

1. Consensus reached on turn N → dispatch fires with (repo, head_sha, pr_number).
2. All ``max_turns`` ran without consensus → dispatch fires.
3. Final turn timed out (not retryable per ``_compute_next_turn``) → dispatch fires.
4. ``post_failed`` mid-loop break → dispatch does NOT fire (re-fire will retry).
5. ``stage='opencode'`` even at max_turns → dispatch does NOT fire.
6. Webhook re-fire on already-consensus stage (early-return path) → dispatch does NOT fire.
7. Webhook re-fire after exhaustion (start_turn>max_turns path) → dispatch does NOT fire.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.gateway.review_loop import ReviewLoop
from src.review.interfaces import ReviewTurnSnapshot
from tests.gateway.test_review_loop import (
    FakeRegistry,
    StubReviewer,
    _finding,
    _ok_result,
)

_PROJECT_ID = uuid.uuid4()
_PR_URL = "https://github.com/owner/repo/pull/42"
_PR_NUMBER = 42
_REPO = "owner/repo"
_SHA = "deadbeef" + "0" * 32
_PATCH_POST_REVIEW = "src.gateway.review_loop.post_review"


def _make_codex_loop(
    reviewer: Any,
    *,
    max_turns: int,
    registry: FakeRegistry,
    ci_dispatcher: Any,
    stage: str = "codex",
    head_sha: str = _SHA,
) -> ReviewLoop:
    return ReviewLoop(
        reviewer,
        max_turns=max_turns,
        registry=registry,
        project_id=_PROJECT_ID,
        pr_url=_PR_URL,
        pr_number=_PR_NUMBER,
        repo_full_name=_REPO,
        head_sha=head_sha,
        stage=stage,
        reviewer_token="fake-token",
        session_index=1,
        max_sessions=5,
        ci_dispatcher=ci_dispatcher,
    )


class TestCodexFinalizationDispatch:
    @pytest.mark.asyncio
    async def test_consensus_fires_dispatch_once(self) -> None:
        """Approved on turn 1 → exactly one dispatch with the right args."""
        dispatcher = AsyncMock()
        stub = StubReviewer(responses=[(_ok_result(verdict="approve"), 1.0, False)])
        registry = FakeRegistry()
        loop = _make_codex_loop(stub, max_turns=3, registry=registry, ci_dispatcher=dispatcher)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        assert outcome.consensus_reached is True
        dispatcher.assert_awaited_once_with(
            repo_full_name=_REPO, head_sha=_SHA, pr_number=_PR_NUMBER
        )

    @pytest.mark.asyncio
    async def test_max_turns_no_consensus_fires_dispatch(self) -> None:
        """Codex burns through all max_turns with new findings each turn → dispatch."""
        dispatcher = AsyncMock()
        stub = StubReviewer(
            responses=[
                (_ok_result(findings=[_finding(line=i, title=f"f{i}")]), 1.0, False)
                for i in range(1, 4)
            ]
        )
        registry = FakeRegistry()
        loop = _make_codex_loop(stub, max_turns=3, registry=registry, ci_dispatcher=dispatcher)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        assert outcome.consensus_reached is False
        assert outcome.turns_used == 3
        dispatcher.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_final_turn_timed_out_fires_dispatch(self) -> None:
        """Last turn timed_out (not retryable) → dispatch fires (terminal)."""
        dispatcher = AsyncMock()
        stub = StubReviewer(
            responses=[
                (_ok_result(findings=[_finding(line=1, title="f1")]), 1.0, False),
                (None, 300.0, True),  # turn 2 times out — not retryable
            ]
        )
        registry = FakeRegistry()
        loop = _make_codex_loop(stub, max_turns=2, registry=registry, ci_dispatcher=dispatcher)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        # turns_used==2 (final turn timed out, no consensus, no post_failed)
        assert outcome.turns_used == 2
        assert outcome.consensus_reached is False
        dispatcher.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_post_failed_mid_loop_does_not_fire(self) -> None:
        """A GitHub POST failure breaks early; webhook re-fire resumes that
        turn (status=='failed' → reset_to_running). Dispatching now would let
        CI race the not-yet-final review, so the hook must NOT fire.
        """
        dispatcher = AsyncMock()
        stub = StubReviewer(
            responses=[(_ok_result(findings=[_finding(line=1, title="x")]), 1.0, False)]
        )
        registry = FakeRegistry()
        loop = _make_codex_loop(stub, max_turns=3, registry=registry, ci_dispatcher=dispatcher)

        # post_review → False on every attempt (twice retried internally, then drop).
        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=False)):
            outcome = await loop.run(diff="d")

        assert any("post_failed" in e for e in outcome.errors)
        dispatcher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_turn_at_max_turns_does_not_fire(self) -> None:
        """Codex subprocess crash / parse error on the final turn records a
        ``status='failed'`` row that ``_compute_next_turn`` would resume on
        webhook re-fire — so the stage is NOT terminal even though
        ``turns_used == max_turns``. Dispatching now would let CI race a
        review the system still considers rerunnable. PR #294 codex review
        caught this regression in the original ``post_failed``-only check.
        """
        dispatcher = AsyncMock()
        stub = StubReviewer(
            responses=[
                (_ok_result(findings=[_finding(line=1, title="f1")]), 1.0, False),
                (None, 2.0, False),  # turn 2: subprocess crash, NOT a timeout
            ]
        )
        registry = FakeRegistry()
        loop = _make_codex_loop(stub, max_turns=2, registry=registry, ci_dispatcher=dispatcher)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        assert outcome.turns_used == 2
        assert any(err.endswith(": failed") for err in outcome.errors)
        dispatcher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_opencode_stage_never_fires_dispatch(self) -> None:
        """Stage A (opencode) is advisory and must not gate CI."""
        dispatcher = AsyncMock()
        stub = StubReviewer(
            responses=[(_ok_result(verdict="approve"), 1.0, False)],
        )
        registry = FakeRegistry()
        loop = _make_codex_loop(
            stub, max_turns=2, registry=registry, ci_dispatcher=dispatcher, stage="opencode"
        )

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        assert outcome.consensus_reached is True
        dispatcher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refire_already_at_consensus_does_not_fire(self) -> None:
        """The early-return path at line ~351 (consensus already recorded) is
        a webhook re-fire — the original firing already dispatched. The hook
        must NOT double-fire on resumed runs.
        """
        dispatcher = AsyncMock()
        registry = FakeRegistry()
        # Pre-seed a completed turn that already reached consensus.
        registry._turns[(_PR_URL, _SHA, "codex", 1)] = ReviewTurnSnapshot(
            project_id=_PROJECT_ID,
            pr_url=_PR_URL,
            pr_number=_PR_NUMBER,
            head_sha=_SHA,
            stage="codex",
            turn_number=1,
            status="completed",
            finding_count=0,
            consensus_reached=True,
            elapsed_seconds=1.0,
        )
        stub = StubReviewer(responses=[(_ok_result(), 1.0, False)])
        loop = _make_codex_loop(stub, max_turns=3, registry=registry, ci_dispatcher=dispatcher)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        assert outcome.consensus_reached is True
        dispatcher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refire_after_exhaustion_does_not_fire(self) -> None:
        """When prior turns already filled all max_turns slots without
        consensus, ``start_turn > max_turns`` short-circuits before the
        loop body. The original exhaustion firing dispatched; this re-fire
        must not.
        """
        dispatcher = AsyncMock()
        registry = FakeRegistry()
        for i in (1, 2, 3):
            registry._turns[(_PR_URL, _SHA, "codex", i)] = ReviewTurnSnapshot(
                project_id=_PROJECT_ID,
                pr_url=_PR_URL,
                pr_number=_PR_NUMBER,
                head_sha=_SHA,
                stage="codex",
                turn_number=i,
                status="completed",
                finding_count=1,
                consensus_reached=False,
                elapsed_seconds=1.0,
            )
        stub = StubReviewer(responses=[(_ok_result(), 1.0, False)])
        loop = _make_codex_loop(stub, max_turns=3, registry=registry, ci_dispatcher=dispatcher)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        assert outcome.turns_used == 0
        dispatcher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_dispatcher_is_safe(self) -> None:
        """``ci_dispatcher=None`` (default for non-codex callers) is a no-op."""
        stub = StubReviewer(responses=[(_ok_result(verdict="approve"), 1.0, False)])
        registry = FakeRegistry()
        loop = _make_codex_loop(stub, max_turns=3, registry=registry, ci_dispatcher=None)

        with patch(_PATCH_POST_REVIEW, new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="d")

        assert outcome.consensus_reached is True
