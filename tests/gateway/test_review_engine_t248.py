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

    def test_codex_schema_with_null_status_parses(self) -> None:
        """T-264: schema now requires ``status`` in ``required`` with type
        ``["string", "null"]``. Verify that an explicit ``null`` parses to
        ``ReviewResult.status = None`` without exploding the validator."""
        raw = json.dumps(
            {
                "overall_correctness": "patch is correct",
                "overall_explanation": "Looks good",
                "status": None,
                "findings": [],
            }
        )
        result = parse_reviewer_output(raw, pr_number=42)
        assert result is not None
        assert result.status is None
        assert result.verdict == "approve"

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


# ---------------------------------------------------------------------------
# Opencode bot identity — hard-coded constants (matches _CLAUDE/_CODEX pattern)
# ---------------------------------------------------------------------------


class TestOpencodeTokenPath:
    """The opencode App ID and installation ID live as hard-coded constants
    in ``src.gateway.github_token`` — same precedent as the claude and codex
    reviewer bots. Only the PEM is per-host. Regression guard: these tests
    pin that the token path uses the hard-coded constants and that a missing
    PEM raises ``FileNotFoundError`` (which the sequencer catches to degrade
    to codex-only)."""

    def test_app_id_and_installation_id_are_constants(self) -> None:
        from src.gateway import github_token as gt

        assert gt._OPENCODE_APP_ID, "App ID must be a non-empty constant"
        assert gt._OPENCODE_INSTALLATION_ID, "Installation ID must be a non-empty constant"
        # Paired PEM path shape — per-host, not per-environment.
        assert gt._OPENCODE_PEM.name == "opencode-reviewer.pem"
        assert gt._OPENCODE_PEM.parent.name == "credentials"
        assert gt._OPENCODE_PEM.parent.parent.name == ".agent-vm"

    @pytest.mark.asyncio
    async def test_missing_pem_raises_file_not_found(self) -> None:
        """On a host that hasn't provisioned the PEM, token fetch raises
        FileNotFoundError (which ``_review_pr`` catches to skip stage A)."""
        from pathlib import Path
        from unittest.mock import patch

        from src.gateway import github_token as gt

        gt.reset_token_cache()
        with (
            patch.object(gt, "_OPENCODE_PEM", Path("/nonexistent/opencode-reviewer.pem")),
            pytest.raises(FileNotFoundError),
        ):
            await gt.get_opencode_reviewer_token()
        gt.reset_token_cache()

    @pytest.mark.asyncio
    async def test_constants_drive_token_request(self) -> None:
        """Patches the shared ``_get_token`` and asserts the hard-coded
        App ID + installation ID are passed through (no env / Settings lookup)."""
        from unittest.mock import AsyncMock, patch

        from src.gateway import github_token as gt

        gt.reset_token_cache()
        captured: dict[str, str] = {}

        async def fake_get(
            app_id: str,
            installation_id: str,
            *args: object,
            **kwargs: object,
        ) -> str:
            captured["app_id"] = app_id
            captured["installation_id"] = installation_id
            return "fake-token"

        try:
            with patch.object(gt, "_get_token", new=AsyncMock(side_effect=fake_get)):
                token = await gt.get_opencode_reviewer_token()
            assert token == "fake-token"
            assert captured["app_id"] == gt._OPENCODE_APP_ID
            assert captured["installation_id"] == gt._OPENCODE_INSTALLATION_ID
        finally:
            gt.reset_token_cache()


# ---------------------------------------------------------------------------
# PR #187 round 1 HIGH-2 — opencode-only host must not require codex token
# ---------------------------------------------------------------------------


class TestOpencodeOnlyHost:
    """Regression guard: on an opencode-only host, ``_review_pr`` must NOT call
    ``get_codex_reviewer_token()`` before any stage runs. Previously, the
    unconditional codex token fetch blew up before stage A, defeating the
    advertised registration-matrix ``opencode-only`` mode (spec §5.4)."""

    @pytest.mark.asyncio
    async def test_session_cap_check_skipped_when_codex_unavailable(self) -> None:
        """With codex_available=False, count_bot_reviews MUST NOT be called."""
        from unittest.mock import AsyncMock, patch

        from src.gateway.review_engine import ReviewEngineConsumer

        consumer = ReviewEngineConsumer(
            codex_available=False,
            opencode_available=True,
            session_factory=None,  # fall-through degraded path
        )

        with (
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-token"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(side_effect=RuntimeError("should not be called")),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(side_effect=RuntimeError("cap not applicable to opencode-only")),
            ),
            patch.object(
                consumer,
                "_fetch_pr_diff",
                new=AsyncMock(return_value=""),
            ),
        ):
            # Empty filtered diff → skip comment path; but the cap check and
            # codex-token fetch are both BEFORE the diff check. If either runs,
            # the RuntimeError above surfaces. This test asserts neither fires.
            await consumer._review_pr(_event(sender="human-user"))


# ---------------------------------------------------------------------------
# PR #187 round 2 CRITICAL — Gateway must not import Review's repository
# ---------------------------------------------------------------------------


class TestGatewayReviewContextBoundary:
    """DDD priority-3 guard: Gateway code must only import Review's
    ``interfaces`` or ``services`` modules — never ``models`` or ``repository``.

    Previously ``src/gateway/review_engine.py::_RegistryCtx.__aenter__`` did
    ``from src.review.repository import ReviewTurnRepository`` (a lazy import
    but still a cross-context-internal dependency). PR #187 round 2 CRITICAL
    moved Gateway to use ``src.review.services.make_review_turn_registry``
    as the Open Host Service entry point; this test pins that invariant.
    """

    def test_gateway_code_does_not_import_review_repository(self) -> None:
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "gateway"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text()
            if "from src.review.repository" in text:
                offenders.append(str(path.relative_to(root.parent.parent)))
            if "import src.review.repository" in text:
                offenders.append(str(path.relative_to(root.parent.parent)))
        assert offenders == [], (
            f"Gateway modules must not import src.review.repository directly "
            f"(use src.review.services instead). Offenders: {offenders}"
        )

    def test_gateway_code_does_not_import_review_models(self) -> None:
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "gateway"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text()
            if "from src.review.models" in text or "import src.review.models" in text:
                offenders.append(str(path.relative_to(root.parent.parent)))
        assert offenders == [], (
            f"Gateway modules must not import src.review.models directly. Offenders: {offenders}"
        )
