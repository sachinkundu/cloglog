"""Additional tests for T-248-specific changes to review_engine.py.

Covers:
- _REVIEWER_BOTS guard in ReviewEngineConsumer.handles() (spec §4.1 criterion 6)
- ReviewResult.status field (optional, validated)
- ReviewFinding.title field (optional, defaults to "")
- parse_reviewer_output: Codex-schema WITH and WITHOUT status
- is_opencode_available()
- count_bot_reviews: distinct commit_id counting (spec §6.3) and fallback
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from src.gateway.review_engine import (
    _CLAUDE_BOT,
    _CODEX_BOT,
    _OPENCODE_BOT,
    ReviewEngineConsumer,
    ReviewFinding,
    ReviewResult,
    count_bot_reviews,
    is_opencode_available,
    parse_reviewer_output,
)
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    event_type: WebhookEventType = WebhookEventType.PR_OPENED,
    *,
    sender: str = "human-user",
    pr_number: int = 42,
) -> WebhookEvent:
    return WebhookEvent(
        type=event_type,
        delivery_id=f"d-{pr_number}",
        repo_full_name="owner/repo",
        pr_number=pr_number,
        pr_url=f"https://github.com/owner/repo/pull/{pr_number}",
        head_branch="feature-branch",
        base_branch="main",
        sender=sender,
        raw={},
    )


# ---------------------------------------------------------------------------
# _REVIEWER_BOTS guard in handles()  (spec §4.1 criterion 6)
# ---------------------------------------------------------------------------


class TestHandlesReviewerBotGuard:
    def test_skips_opencode_reviewer_bot(self) -> None:
        """PRs authored by cloglog-opencode-reviewer[bot] must not be reviewed (loop guard)."""
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_OPENED, sender=_OPENCODE_BOT)
        assert consumer.handles(event) is False

    def test_skips_codex_reviewer_bot(self) -> None:
        """PRs authored by cloglog-codex-reviewer[bot] must not be reviewed."""
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_OPENED, sender=_CODEX_BOT)
        assert consumer.handles(event) is False

    def test_still_reviews_claude_bot_prs(self) -> None:
        """PRs from the code-push bot (sakundu-claude-assistant[bot]) SHOULD be reviewed."""
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_OPENED, sender=_CLAUDE_BOT)
        assert consumer.handles(event) is True

    def test_still_reviews_human_prs(self) -> None:
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_OPENED, sender="some-developer")
        assert consumer.handles(event) is True

    def test_skips_opencode_bot_on_synchronize(self) -> None:
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_SYNCHRONIZE, sender=_OPENCODE_BOT)
        assert consumer.handles(event) is False


# ---------------------------------------------------------------------------
# ReviewResult.status
# ---------------------------------------------------------------------------


class TestReviewResultStatus:
    def test_no_further_concerns_accepted(self) -> None:
        r = ReviewResult(
            verdict="approve",
            summary="done",
            findings=[],
            status="no_further_concerns",
        )
        assert r.status == "no_further_concerns"

    def test_review_in_progress_accepted(self) -> None:
        r = ReviewResult(
            verdict="comment",
            summary="still looking",
            findings=[],
            status="review_in_progress",
        )
        assert r.status == "review_in_progress"

    def test_none_status_accepted(self) -> None:
        r = ReviewResult(verdict="approve", summary="ok", findings=[], status=None)
        assert r.status is None

    def test_status_absent_defaults_to_none(self) -> None:
        r = ReviewResult(verdict="approve", summary="ok", findings=[])
        assert r.status is None

    def test_bogus_status_raises(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ReviewResult(verdict="approve", summary="", findings=[], status="bogus")


# ---------------------------------------------------------------------------
# ReviewFinding.title
# ---------------------------------------------------------------------------


class TestReviewFindingTitle:
    def test_title_defaults_to_empty_string(self) -> None:
        f = ReviewFinding(file="a.py", line=1, severity="low", body="issue")
        assert f.title == ""

    def test_title_explicit_value(self) -> None:
        f = ReviewFinding(file="a.py", line=1, severity="high", body="issue", title="SQL injection")
        assert f.title == "SQL injection"


# ---------------------------------------------------------------------------
# parse_reviewer_output  (module-level helper, T-248 Codex-schema path)
# ---------------------------------------------------------------------------


class TestParseReviewerOutput:
    def test_internal_schema_parses(self) -> None:
        raw = json.dumps(
            {
                "verdict": "approve",
                "summary": "clean",
                "findings": [],
            }
        )
        result = parse_reviewer_output(raw, pr_number=1)
        assert result is not None
        assert result.verdict == "approve"

    def test_codex_schema_with_status_preserves_status(self) -> None:
        """Codex schema WITH top-level status → status must be preserved (regression guard,
        the MEDIUM finding from PR #185 round 1)."""
        raw = json.dumps(
            {
                "overall_correctness": "patch is correct",
                "overall_explanation": "Looks good",
                "status": "no_further_concerns",
                "findings": [],
            }
        )
        result = parse_reviewer_output(raw, pr_number=2)
        assert result is not None
        assert result.status == "no_further_concerns"
        assert result.verdict == "approve"

    def test_codex_schema_without_status_backward_compat(self) -> None:
        """Codex schema WITHOUT status field → still parses cleanly."""
        raw = json.dumps(
            {
                "overall_correctness": "patch needs changes",
                "overall_explanation": "Fix the null check",
                "findings": [
                    {
                        "code_location": {
                            "absolute_file_path": "src/x.py",
                            "line_range": {"start": 10, "end": 12},
                        },
                        "priority": 2,
                        "title": "Null pointer",
                        "body": "Missing null check on line 10",
                    }
                ],
            }
        )
        result = parse_reviewer_output(raw, pr_number=3)
        assert result is not None
        assert result.status is None
        assert result.verdict == "request_changes"
        assert len(result.findings) == 1
        assert result.findings[0].title == "Null pointer"

    def test_returns_none_on_invalid_json(self) -> None:
        assert parse_reviewer_output("not json at all", pr_number=4) is None

    def test_returns_none_on_schema_violation(self) -> None:
        raw = json.dumps({"verdict": "bad_verdict", "summary": "", "findings": []})
        assert parse_reviewer_output(raw, pr_number=5) is None

    def test_extracts_embedded_json(self) -> None:
        """Parser extracts JSON embedded in surrounding text (opencode output style)."""
        inner = json.dumps({"verdict": "comment", "summary": "noted", "findings": []})
        raw = f"some preamble text\n{inner}\nand a trailing line"
        result = parse_reviewer_output(raw, pr_number=6)
        assert result is not None
        assert result.verdict == "comment"


# ---------------------------------------------------------------------------
# is_opencode_available
# ---------------------------------------------------------------------------


class TestIsOpencodeAvailable:
    def test_returns_true_when_on_path(self) -> None:
        with patch(
            "src.gateway.review_engine.shutil.which",
            return_value="/usr/local/bin/opencode",
        ):
            assert is_opencode_available() is True

    def test_returns_false_when_not_on_path(self) -> None:
        with patch("src.gateway.review_engine.shutil.which", return_value=None):
            assert is_opencode_available() is False


# ---------------------------------------------------------------------------
# count_bot_reviews — distinct commit_id counting (spec §6.3)
# ---------------------------------------------------------------------------


class TestCountBotReviews:
    @pytest.mark.asyncio
    @respx.mock
    async def test_counts_distinct_commit_ids(self) -> None:
        """3 review POSTs on 2 distinct commit_ids → count = 2 (session count)."""
        reviews = [
            {"user": {"login": _CODEX_BOT}, "commit_id": "sha_a"},
            {"user": {"login": _CODEX_BOT}, "commit_id": "sha_a"},  # same commit as above
            {"user": {"login": _CODEX_BOT}, "commit_id": "sha_b"},
        ]
        respx.get("https://api.github.com/repos/owner/repo/pulls/1/reviews").mock(
            return_value=httpx.Response(200, json=reviews)
        )

        async with httpx.AsyncClient() as client:
            count = await count_bot_reviews("owner/repo", 1, "fake-token", client=client)

        assert count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_row_count_when_no_commit_ids(self) -> None:
        """If ALL codex rows lack commit_id, fall back to counting rows (back-compat)."""
        reviews = [
            {"user": {"login": _CODEX_BOT}},
            {"user": {"login": _CODEX_BOT}},
            {"user": {"login": _CODEX_BOT}},
        ]
        respx.get("https://api.github.com/repos/owner/repo/pulls/2/reviews").mock(
            return_value=httpx.Response(200, json=reviews)
        )

        async with httpx.AsyncClient() as client:
            count = await count_bot_reviews("owner/repo", 2, "fake-token", client=client)

        assert count == 3

    @pytest.mark.asyncio
    @respx.mock
    async def test_ignores_non_codex_reviews(self) -> None:
        """Only cloglog-codex-reviewer[bot] reviews count."""
        reviews = [
            {"user": {"login": "some-human"}, "commit_id": "sha_a"},
            {"user": {"login": _CODEX_BOT}, "commit_id": "sha_b"},
        ]
        respx.get("https://api.github.com/repos/owner/repo/pulls/3/reviews").mock(
            return_value=httpx.Response(200, json=reviews)
        )

        async with httpx.AsyncClient() as client:
            count = await count_bot_reviews("owner/repo", 3, "fake-token", client=client)

        assert count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_zero_when_no_bot_reviews(self) -> None:
        respx.get("https://api.github.com/repos/owner/repo/pulls/4/reviews").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with httpx.AsyncClient() as client:
            count = await count_bot_reviews("owner/repo", 4, "fake-token", client=client)

        assert count == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_distinct_commit_ids_single_post_per_commit(self) -> None:
        """1 review per commit_id → count equals number of distinct shas."""
        reviews = [
            {"user": {"login": _CODEX_BOT}, "commit_id": "sha1"},
            {"user": {"login": _CODEX_BOT}, "commit_id": "sha2"},
        ]
        respx.get("https://api.github.com/repos/owner/repo/pulls/5/reviews").mock(
            return_value=httpx.Response(200, json=reviews)
        )

        async with httpx.AsyncClient() as client:
            count = await count_bot_reviews("owner/repo", 5, "fake-token", client=client)

        assert count == 2
