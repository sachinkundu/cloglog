"""T-367: cross-push memory + exhaustive single-pass codex tests.

Covers:
- One codex turn per webhook (codex_max_turns=1) so the loop calls the reviewer
  exactly once and does NOT re-invoke for a phantom turn 2.
- Findings + learnings persisted to the registry on a successful turn.
- Prior-turn findings + learnings are rendered into the codex prompt preamble
  by ``build_codex_prompt`` (next turn's input).
- PR body injection — present body and missing body shapes.
- Topic-based dedup of learnings across turns (last-write-wins on note).

These tests use the in-memory ``FakeRegistry`` from ``test_review_loop`` and the
real ``build_codex_prompt`` renderer (no subprocess). They are integration tests
in the cloglog sense: real persistence shape + real renderer + stubbed reviewer.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.gateway.review_engine import ReviewFinding, ReviewResult
from src.gateway.review_loop import (
    CodexReviewer,
    ReviewLoop,
    _dedupe_learnings,
    _render_pr_body_section,
    _render_prior_history_section,
    build_codex_prompt,
)
from src.review.interfaces import PriorContext, PriorTurnSummary
from tests.gateway.test_review_loop import FakeRegistry, StubReviewer

_PROJECT_ID = uuid.uuid4()
_PR_URL = "https://github.com/owner/repo/pull/367"
_PR_NUMBER = 367
_REPO = "owner/repo"
_SHA_1 = "a" * 40
_SHA_2 = "b" * 40


def _result(
    findings: list[ReviewFinding] | None = None,
    learnings: list[dict[str, Any]] | None = None,
) -> ReviewResult:
    return ReviewResult(
        verdict="comment",
        summary="ok",
        findings=findings or [],
        status=None,
        learnings=learnings or [],
    )


def _finding(file: str = "x.py", line: int = 10, title: str = "issue") -> ReviewFinding:
    return ReviewFinding(file=file, line=line, severity="medium", body="see title", title=title)


def _make_loop(
    reviewer: Any,
    *,
    registry: FakeRegistry,
    head_sha: str = _SHA_1,
    max_turns: int = 1,
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
        stage="codex",
        reviewer_token="fake-token",
        session_index=1,
        max_sessions=5,
    )


# ---------------------------------------------------------------------------
# Section 7 §1: one codex turn per webhook
# ---------------------------------------------------------------------------


class TestSingleTurnPerWebhook:
    """``codex_max_turns=1`` → ReviewLoop calls ``Reviewer.run`` exactly once,
    never twice. This is the invariant that retired the wasteful per-webhook
    second turn (T-367 §3.3)."""

    @pytest.mark.asyncio
    async def test_codex_loop_runs_reviewer_exactly_once(self) -> None:
        registry = FakeRegistry()
        reviewer = StubReviewer(responses=[(_result(findings=[_finding()]), 1.0, False)])
        loop = _make_loop(reviewer, registry=registry, max_turns=1)
        with patch("src.gateway.review_loop.post_review", new=AsyncMock(return_value=True)):
            outcome = await loop.run(diff="diff --git a/x.py b/x.py\n")
        assert reviewer._call_count == 1, (
            f"With codex_max_turns=1 the loop must invoke the reviewer once, "
            f"got {reviewer._call_count}. T-367 §3.3 regression: a back-to-back "
            "second turn wastes a paid codex invocation."
        )
        assert outcome.turns_used == 1


# ---------------------------------------------------------------------------
# Section 7 §3: persistence — findings_json + learnings_json round-trip
# ---------------------------------------------------------------------------


class TestRecordFindingsAndLearnings:
    """A successful turn must call ``record_findings_and_learnings`` on the
    registry so cross-push replay has something to read. Both arrays should
    be persisted exactly as the reviewer emitted them (after model_dump for
    findings)."""

    @pytest.mark.asyncio
    async def test_findings_and_learnings_persisted_after_complete_turn(self) -> None:
        registry = FakeRegistry()
        learning = {
            "topic": "DDD: Review boundary",
            "note": "Gateway calls Review only via interfaces.py",
        }
        reviewer = StubReviewer(
            responses=[(_result(findings=[_finding()], learnings=[learning]), 1.5, False)]
        )
        loop = _make_loop(reviewer, registry=registry, max_turns=1)
        with patch("src.gateway.review_loop.post_review", new=AsyncMock(return_value=True)):
            await loop.run(diff="diff --git a/x.py b/x.py\n")

        prior = await registry.prior_findings_and_learnings(pr_url=_PR_URL, stage="codex")
        assert len(prior.turns) == 1
        only = prior.turns[0]
        assert only.findings and only.findings[0]["title"] == "issue"
        assert only.learnings == [learning]

    @pytest.mark.asyncio
    async def test_failed_turn_does_not_persist_findings(self) -> None:
        """A turn whose reviewer returned None (timeout/parse fail) must NOT
        leave a stub findings row that prior_findings_and_learnings would
        replay as 'this turn found nothing.'"""
        registry = FakeRegistry()
        reviewer = StubReviewer(responses=[(None, 0.5, True)])
        loop = _make_loop(reviewer, registry=registry, max_turns=1)
        with patch("src.gateway.review_loop.post_review", new=AsyncMock(return_value=True)):
            await loop.run(diff="diff --git a/x.py b/x.py\n")

        prior = await registry.prior_findings_and_learnings(pr_url=_PR_URL, stage="codex")
        assert prior.turns == [], (
            "A failed/timed-out turn must NOT surface in prior context — "
            "it has nothing to replay. FakeRegistry filters by both "
            "status='completed' AND non-null findings_json."
        )


# ---------------------------------------------------------------------------
# Section 7 §4: prompt assembly contains prior findings + PR body
# ---------------------------------------------------------------------------


class TestBuildCodexPrompt:
    """The pure renderer used by ``CodexReviewer.run``. Pin the rendered
    shape so a future drift in section headers immediately fails — codex's
    prompt is a behavioral contract."""

    def test_pr_body_section_renders_when_body_present(self) -> None:
        out = _render_pr_body_section("## Task\nT-367 — codex memory")
        assert "## What this PR is doing" in out
        assert "T-367 — codex memory" in out

    def test_pr_body_section_handles_missing_body(self) -> None:
        out = _render_pr_body_section(None)
        assert "no description" in out.lower()
        assert "## What this PR is doing" in out

    def test_pr_body_section_handles_whitespace_only(self) -> None:
        out = _render_pr_body_section("   \n  \t  ")
        assert "no description" in out.lower()

    def test_prior_history_section_empty_when_no_turns(self) -> None:
        empty = PriorContext(pr_url=_PR_URL, turns=[])
        assert _render_prior_history_section(empty) == ""
        assert _render_prior_history_section(None) == ""

    def test_prior_history_section_lists_findings_per_turn(self) -> None:
        ctx = PriorContext(
            pr_url=_PR_URL,
            turns=[
                PriorTurnSummary(
                    head_sha=_SHA_1,
                    turn_number=1,
                    findings=[
                        {
                            "file": "src/gateway/review_engine.py",
                            "line": 42,
                            "severity": "high",
                            "body": "missing await on session commit",
                            "title": "missing await",
                        }
                    ],
                    learnings=[],
                ),
            ],
        )
        out = _render_prior_history_section(ctx)
        assert "## Prior review history" in out
        assert "Turn 1" in out
        assert _SHA_1[:7] in out
        assert "src/gateway/review_engine.py:42" in out
        assert "[HIGH]" in out
        assert "missing await" in out

    def test_prior_history_section_renders_learnings_block_when_present(self) -> None:
        ctx = PriorContext(
            pr_url=_PR_URL,
            turns=[
                PriorTurnSummary(
                    head_sha=_SHA_1,
                    turn_number=1,
                    findings=[],
                    learnings=[
                        {"topic": "Test conftest pin", "note": "tests/conftest.py imports models"},
                    ],
                ),
            ],
        )
        out = _render_prior_history_section(ctx)
        assert "Codebase learnings from prior turns" in out
        assert "Test conftest pin" in out
        assert "tests/conftest.py imports models" in out

    def test_build_codex_prompt_orders_sections(self) -> None:
        prompt = build_codex_prompt(
            base_prompt="BASE PROMPT",
            pr_body="## Task\nT-367",
            prior_context=PriorContext(pr_url=_PR_URL, turns=[]),
            diff="diff body",
        )
        # Order: base → pr body → (no history) → diff
        assert prompt.index("BASE PROMPT") < prompt.index("## What this PR is doing")
        assert prompt.index("## What this PR is doing") < prompt.index("DIFF:")
        assert "DIFF:\ndiff body" in prompt

    def test_build_codex_prompt_includes_history_when_nonempty(self) -> None:
        ctx = PriorContext(
            pr_url=_PR_URL,
            turns=[
                PriorTurnSummary(head_sha=_SHA_1, turn_number=1, findings=[], learnings=[]),
            ],
        )
        prompt = build_codex_prompt(base_prompt="BASE", pr_body="body", prior_context=ctx, diff="d")
        assert "## Prior review history" in prompt
        # History block sits between PR body and diff
        assert prompt.index("## What this PR is doing") < prompt.index("## Prior review history")
        assert prompt.index("## Prior review history") < prompt.index("DIFF:")


# ---------------------------------------------------------------------------
# Section 7 §5: dedup learnings by topic across turns
# ---------------------------------------------------------------------------


class TestDedupeLearnings:
    def test_same_topic_across_turns_collapses_to_one(self) -> None:
        turns = [
            PriorTurnSummary(
                head_sha=_SHA_1,
                turn_number=1,
                findings=[],
                learnings=[{"topic": "DDD boundary", "note": "old note"}],
            ),
            PriorTurnSummary(
                head_sha=_SHA_2,
                turn_number=2,
                findings=[],
                learnings=[{"topic": "DDD boundary", "note": "fresher framing"}],
            ),
        ]
        deduped = _dedupe_learnings(turns)
        assert len(deduped) == 1
        # Last-write-wins on note — the freshest framing of the same fact wins.
        assert deduped[0]["note"] == "fresher framing"

    def test_distinct_topics_preserved_in_first_seen_order(self) -> None:
        turns = [
            PriorTurnSummary(
                head_sha=_SHA_1,
                turn_number=1,
                findings=[],
                learnings=[
                    {"topic": "topic A", "note": "noteA"},
                    {"topic": "topic B", "note": "noteB"},
                ],
            ),
        ]
        deduped = _dedupe_learnings(turns)
        assert [d["topic"] for d in deduped] == ["topic A", "topic B"]

    def test_blank_topic_or_note_dropped(self) -> None:
        turns = [
            PriorTurnSummary(
                head_sha=_SHA_1,
                turn_number=1,
                findings=[],
                learnings=[
                    {"topic": "", "note": "x"},
                    {"topic": "real", "note": ""},
                    {"topic": "valid", "note": "y"},
                ],
            ),
        ]
        deduped = _dedupe_learnings(turns)
        assert deduped == [{"topic": "valid", "note": "y"}]


# ---------------------------------------------------------------------------
# CodexReviewer signature pin — accepts prior_context and pr_body kwargs
# ---------------------------------------------------------------------------


class TestCodexReviewerAcceptsKwargs:
    """A regression that drops the new kwargs from CodexReviewer.run would
    silently break cross-push memory (the loop would still pass the kwargs
    but the renderer would never see them). Pin the signature."""

    def test_codex_reviewer_run_accepts_prior_context_and_pr_body(self, tmp_path: Any) -> None:
        import inspect

        sig = inspect.signature(CodexReviewer.run)
        params = sig.parameters
        assert "prior_context" in params, (
            "CodexReviewer.run must accept prior_context kwarg — T-367 §3.4"
        )
        assert "pr_body" in params, "CodexReviewer.run must accept pr_body kwarg — T-367 §3.1/§3.4"
