"""Tests for the F-36 ReviewEngineConsumer and its helpers.

Covers both T-192 (consumer core, filter_diff, rate limit, handles guard,
orchestration with subprocess mocked) and T-193 (diff-line mapping,
post_review retry semantics, end-to-end consumer → GitHub review API
integration with both ends mocked).

Real subprocesses and real GitHub API calls are never made — ``_spawn``
is patched and ``respx.mock`` captures the reviews POST. A manual E2E
recipe lives at ``docs/review-engine-e2e.md``.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from pydantic import ValidationError

from src.gateway.review_engine import (
    _CLAUDE_BOT,
    _CODEX_BOT,
    MAX_DIFF_CHARS,
    MAX_REVIEWS_PER_PR,
    RATE_LIMIT_WINDOW_SECONDS,
    RateLimiter,
    ReviewEngineConsumer,
    ReviewFinding,
    ReviewResult,
    _format_review_body,
    _partition_findings,
    count_bot_reviews,
    extract_diff_new_lines,
    filter_diff,
    is_review_agent_available,
    log_review_source_root,
    parse_review_output,
    post_review,
    resolve_review_source_root,
)
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestReviewModels:
    def test_finding_accepts_allowed_severity(self) -> None:
        f = ReviewFinding(file="a.py", line=1, severity="high", body="issue")
        assert f.severity == "high"

    def test_finding_rejects_unknown_severity(self) -> None:
        with pytest.raises(ValidationError):
            ReviewFinding(file="a.py", line=1, severity="meh", body="x")

    def test_result_accepts_allowed_verdict_and_nested_findings(self) -> None:
        result = ReviewResult(
            verdict="request_changes",
            summary="has bugs",
            findings=[ReviewFinding(file="a.py", line=1, severity="high", body="x")],
        )
        assert result.verdict == "request_changes"
        assert len(result.findings) == 1

    def test_result_rejects_unknown_verdict(self) -> None:
        with pytest.raises(ValidationError):
            ReviewResult(verdict="merge_it", summary="", findings=[])

    def test_empty_findings_allowed(self) -> None:
        result = ReviewResult(verdict="approve", summary="clean", findings=[])
        assert result.findings == []


# ---------------------------------------------------------------------------
# parse_review_output
# ---------------------------------------------------------------------------


class TestParseReviewOutput:
    def test_parses_valid_json(self) -> None:
        raw = json.dumps(
            {
                "verdict": "approve",
                "summary": "looks good",
                "findings": [],
            }
        )
        result = parse_review_output(raw)
        assert result is not None
        assert result.verdict == "approve"

    def test_returns_none_on_invalid_json(self) -> None:
        assert parse_review_output("not json") is None

    def test_returns_none_on_schema_violation(self) -> None:
        raw = json.dumps({"verdict": "nope", "summary": "x", "findings": []})
        assert parse_review_output(raw) is None

    def test_returns_none_on_missing_fields(self) -> None:
        assert parse_review_output("{}") is None


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_allows_up_to_max(self) -> None:
        rl = RateLimiter(max_per_hour=3)
        assert rl.allow() is True
        assert rl.allow() is True
        assert rl.allow() is True

    def test_blocks_at_max(self) -> None:
        rl = RateLimiter(max_per_hour=2)
        assert rl.allow() is True
        assert rl.allow() is True
        assert rl.allow() is False

    def test_expired_timestamps_free_up_slots(self) -> None:
        rl = RateLimiter(max_per_hour=2)
        # Prime with two hits in the distant past
        rl._timestamps = [0.0, 0.1]
        # Monotonic is way past RATE_LIMIT_WINDOW_SECONDS from 0.0/0.1,
        # so both should be evicted and allow() should succeed.
        with patch(
            "src.gateway.review_engine.time.monotonic",
            return_value=RATE_LIMIT_WINDOW_SECONDS + 10,
        ):
            assert rl.allow() is True

    def test_recent_timestamps_still_count(self) -> None:
        rl = RateLimiter(max_per_hour=2)
        rl._timestamps = [100.0, 100.5]
        with patch("src.gateway.review_engine.time.monotonic", return_value=200.0):
            # 200 - 100 = 100s, well inside 3600s window
            assert rl.allow() is False


# ---------------------------------------------------------------------------
# filter_diff
# ---------------------------------------------------------------------------


class TestFilterDiff:
    @staticmethod
    def _section(path: str, body: str = "@@ -1 +1 @@\n-old\n+new") -> str:
        return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n{body}"

    def test_keeps_source_files(self) -> None:
        diff = self._section("src/board/models.py") + "\n" + self._section("frontend/src/App.tsx")
        out = filter_diff(diff)
        assert "src/board/models.py" in out
        assert "frontend/src/App.tsx" in out

    def test_drops_package_lock(self) -> None:
        diff = self._section("package-lock.json") + "\n" + self._section("src/board/models.py")
        out = filter_diff(diff)
        assert "package-lock.json" not in out
        assert "src/board/models.py" in out

    def test_drops_generic_lock_files(self) -> None:
        diff = self._section("uv.lock") + "\n" + self._section("src/x.py")
        out = filter_diff(diff)
        assert "uv.lock" not in out
        assert "src/x.py" in out

    def test_drops_generated_types(self) -> None:
        diff = (
            self._section("frontend/src/generated-types.ts")
            + "\n"
            + self._section("frontend/src/App.tsx")
        )
        out = filter_diff(diff)
        assert "generated-types.ts" not in out
        assert "frontend/src/App.tsx" in out

    def test_drops_minified(self) -> None:
        diff = self._section("dist/bundle.min.js") + "\n" + self._section("src/x.py")
        out = filter_diff(diff)
        assert "bundle.min.js" not in out
        assert "src/x.py" in out

    def test_drops_env_files(self) -> None:
        diff = (
            self._section(".env")
            + "\n"
            + self._section(".env.production")
            + "\n"
            + self._section("src/x.py")
        )
        out = filter_diff(diff)
        assert ".env" not in out
        assert ".env.production" not in out
        assert "src/x.py" in out

    def test_drops_credentials_and_keys(self) -> None:
        diff = (
            self._section("credentials/github-app.pem")
            + "\n"
            + self._section("ops/keys/prod.key")
            + "\n"
            + self._section("src/x.py")
        )
        out = filter_diff(diff)
        assert "credentials/github-app.pem" not in out
        assert "prod.key" not in out
        assert "src/x.py" in out

    def test_all_filtered_returns_empty_body(self) -> None:
        diff = self._section("package-lock.json") + "\n" + self._section("a.lock")
        out = filter_diff(diff)
        assert "package-lock.json" not in out
        assert ".lock" not in out
        assert out.strip() == ""

    def test_empty_input(self) -> None:
        assert filter_diff("") == ""

    def test_non_git_preamble_is_preserved(self) -> None:
        """A bare unified diff without a ``diff --git`` header should pass through."""
        diff = "--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"
        out = filter_diff(diff)
        assert out == diff


# ---------------------------------------------------------------------------
# is_review_agent_available
# ---------------------------------------------------------------------------


def test_is_review_agent_available_true_when_on_path() -> None:
    with patch("src.gateway.review_engine.shutil.which", return_value="/usr/bin/codex"):
        assert is_review_agent_available() is True


def test_is_review_agent_available_false_when_missing() -> None:
    with patch("src.gateway.review_engine.shutil.which", return_value=None):
        assert is_review_agent_available() is False


# ---------------------------------------------------------------------------
# ReviewEngineConsumer.handles
# ---------------------------------------------------------------------------


def _event(
    event_type: WebhookEventType = WebhookEventType.PR_OPENED,
    *,
    sender: str = "sachinkundu",
    pr_number: int = 42,
) -> WebhookEvent:
    return WebhookEvent(
        type=event_type,
        delivery_id=f"d-{pr_number}",
        repo_full_name="sachinkundu/cloglog",
        pr_number=pr_number,
        pr_url=f"https://github.com/sachinkundu/cloglog/pull/{pr_number}",
        head_branch="wt-test",
        base_branch="main",
        sender=sender,
        raw={},
    )


class TestHandles:
    def test_accepts_pr_opened(self) -> None:
        consumer = ReviewEngineConsumer()
        assert consumer.handles(_event(WebhookEventType.PR_OPENED)) is True

    def test_accepts_pr_synchronize(self) -> None:
        consumer = ReviewEngineConsumer()
        assert consumer.handles(_event(WebhookEventType.PR_SYNCHRONIZE)) is True

    def test_rejects_pr_closed(self) -> None:
        consumer = ReviewEngineConsumer()
        assert consumer.handles(_event(WebhookEventType.PR_CLOSED)) is False

    def test_rejects_pr_merged(self) -> None:
        consumer = ReviewEngineConsumer()
        assert consumer.handles(_event(WebhookEventType.PR_MERGED)) is False

    def test_rejects_review_submitted(self) -> None:
        consumer = ReviewEngineConsumer()
        assert consumer.handles(_event(WebhookEventType.REVIEW_SUBMITTED)) is False

    def test_self_review_guard_blocks_codex_bot(self) -> None:
        """PR events from the Codex reviewer bot must be skipped to avoid loops."""
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_OPENED, sender=_CODEX_BOT)
        assert consumer.handles(event) is False

    def test_claude_bot_prs_are_reviewed(self) -> None:
        """PRs created by the Claude bot SHOULD be reviewed by Codex."""
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_OPENED, sender=_CLAUDE_BOT)
        assert consumer.handles(event) is True


# ---------------------------------------------------------------------------
# ReviewEngineConsumer.handle — orchestration
# ---------------------------------------------------------------------------


class _FakeProcess:
    """Minimal stand-in for an ``asyncio.subprocess.Process`` used in tests."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        hang: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang
        self.kill_calls = 0

    def kill(self) -> None:
        # After kill, wait() must return promptly (mirrors real subprocess behavior).
        self.kill_calls += 1
        self._hang = False

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:  # noqa: A002
        if self._hang:
            await asyncio.sleep(3600)
        return self._stdout, self._stderr

    async def wait(self) -> int:
        if self._hang:
            await asyncio.sleep(3600)
        return self.returncode


@pytest.fixture
def sample_diff() -> str:
    return "diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"


@pytest.fixture
def sample_review_json() -> str:
    return json.dumps(
        {
            "verdict": "approve",
            "summary": "clean",
            "findings": [],
        }
    )


class TestHandleOrchestration:
    @pytest.fixture(autouse=True)
    def _stub_count_bot_reviews(self) -> Any:
        """Default: no prior bot reviews on this PR. Tests can re-patch locally."""
        with patch(
            "src.gateway.review_engine.count_bot_reviews",
            new=AsyncMock(return_value=0),
        ) as m:
            yield m

    @pytest.mark.asyncio
    async def test_rate_limit_short_circuits(self, caplog: Any) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=0)
        with (
            caplog.at_level("WARNING", logger="src.gateway.review_engine"),
            patch.object(consumer, "_review_pr", new=AsyncMock()) as review,
        ):
            await consumer.handle(_event())

        review.assert_not_called()
        assert any("rate limit exceeded" in r.message.lower() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_happy_path_produces_review_result(
        self, sample_diff: str, sample_review_json: str
    ) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)

        def fake_spawn_factory(diff_bytes: bytes):
            # _spawn is called twice per handle: once for gh pr diff, once for the agent.
            diff_proc = _FakeProcess(stdout=diff_bytes)
            # The agent needs to *write the JSON file* before it exits. We capture
            # the prompt path from the second spawn call so we can locate the
            # output file the agent promised to write.
            calls: list[tuple[str, ...]] = []
            output_path_holder: dict[str, Path] = {}

            async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
                calls.append(argv)
                if argv[0] == "gh":
                    return diff_proc
                pytest.fail("_spawn should only be called for gh, not for codex")

            return _fake_spawn, calls, output_path_holder

        fake_spawn, calls, paths = fake_spawn_factory(sample_diff.encode())

        # The codex invocation uses create_subprocess_exec directly.
        # We mock it to write the review JSON to the -o output path.
        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            argv = args
            # Find the -o flag to get the output path
            for i, arg in enumerate(argv):
                if arg == "-o" and i + 1 < len(argv):
                    output_path = Path(argv[i + 1])
                    output_path.write_text(sample_review_json)
                    paths["path"] = output_path
                    break
            proc = _FakeProcess(stdout=b"")
            # Simulate communicate() returning immediately
            proc._stdin_data = kwargs.get("stdin")
            return proc

        with (
            patch("src.gateway.review_engine._spawn", side_effect=fake_spawn),
            patch(
                "src.gateway.review_engine._create_subprocess",
                side_effect=_fake_create,
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ) as posted,
        ):
            await consumer.handle(_event())

        # One _spawn call for gh pr diff, codex uses create_subprocess_exec
        assert len(calls) == 1
        assert calls[0][:3] == ("gh", "pr", "diff")
        assert "path" in paths  # the agent wrote its review file
        posted.assert_awaited_once()
        assert posted.call_args.args[0] == "sachinkundu/cloglog"
        assert posted.call_args.args[1] == 42
        assert posted.call_args.args[2].verdict == "approve"

    @pytest.mark.asyncio
    async def test_empty_filtered_diff_skips_agent(self) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)
        # A diff made entirely of lockfiles filters to empty — agent must not run.
        only_lock = (
            "diff --git a/package-lock.json b/package-lock.json\n"
            "--- a/package-lock.json\n"
            "+++ b/package-lock.json\n"
            "@@ -1 +1 @@\n-x\n+y\n"
        )
        calls: list[tuple[str, ...]] = []

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            calls.append(argv)
            if argv[0] == "gh":
                return _FakeProcess(stdout=only_lock.encode())
            pytest.fail("Review agent must not be launched when diff is empty")

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
        ):
            await consumer.handle(_event())

        assert len(calls) == 1  # only the diff fetch ran

    @pytest.mark.asyncio
    async def test_oversized_diff_skips_agent(self) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)
        # Build an ungodly big diff that survives filtering
        big_body = "x" * (MAX_DIFF_CHARS + 100)
        huge_diff = (
            "diff --git a/src/big.py b/src/big.py\n"
            "--- a/src/big.py\n"
            "+++ b/src/big.py\n"
            f"@@ -1 +1 @@\n-{big_body}\n+{big_body}\n"
        )
        calls: list[tuple[str, ...]] = []

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            calls.append(argv)
            if argv[0] == "gh":
                return _FakeProcess(stdout=huge_diff.encode())
            pytest.fail("Review agent must not be launched for oversized diff")

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
        ):
            await consumer.handle(_event())

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_agent_timeout_returns_none_without_crashing(self, sample_diff: str) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)
        diff_proc = _FakeProcess(stdout=sample_diff.encode())
        agent_proc = _FakeProcess(hang=True)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return diff_proc
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            return agent_proc

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_SECONDS", 0.01),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
        ):
            await consumer.handle(_event())

        assert agent_proc.kill_calls >= 1

    @pytest.mark.asyncio
    async def test_missing_output_file_returns_none(self, sample_diff: str) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            # Agent exits 0 but writes nothing to the output file
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
        ):
            # Should complete without raising
            await consumer.handle(_event())

    @pytest.mark.asyncio
    async def test_unparseable_output_returns_none(self, sample_diff: str) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text("NOT JSON")
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
        ):
            await consumer.handle(_event())

    @pytest.mark.asyncio
    async def test_gh_pr_diff_failure_logged_not_raised(self) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            return _FakeProcess(stdout=b"", stderr=b"auth failed", returncode=1)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
        ):
            # handle() must swallow the RuntimeError internally (log + move on)
            await consumer.handle(_event())

    @pytest.mark.asyncio
    async def test_sequential_lock_serializes_two_prs(self, sample_diff: str) -> None:
        """Two concurrent PR events must run one at a time under the asyncio Lock."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        active = 0
        max_active = 0

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            nonlocal active, max_active
            if argv[0] == "gh":
                active += 1
                max_active = max(max_active, active)
                await asyncio.sleep(0.05)
                active -= 1
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(
                        json.dumps({"verdict": "approve", "summary": "ok", "findings": []})
                    )
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ),
        ):
            await asyncio.gather(
                consumer.handle(_event(pr_number=1)),
                consumer.handle(_event(pr_number=2)),
            )

        assert max_active == 1, "Sequential lock did not serialize concurrent reviews"

    @pytest.mark.asyncio
    async def test_codex_argv_uses_bypass_flag_not_sandbox(
        self, sample_diff: str, sample_review_json: str
    ) -> None:
        """Regression guard: codex must be invoked with
        --dangerously-bypass-approvals-and-sandbox and MUST NOT carry --sandbox
        or --full-auto. Any --sandbox mode (including danger-full-access) fails
        on this host because bwrap's unshare-net requires CAP_NET_ADMIN.
        """
        consumer = ReviewEngineConsumer(max_per_hour=10)
        captured_argv: list[tuple[str, ...]] = []

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            captured_argv.append(args)
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(sample_review_json)
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ),
        ):
            await consumer.handle(_event())

        assert len(captured_argv) == 1, "codex must be invoked exactly once"
        argv = captured_argv[0]
        assert "--dangerously-bypass-approvals-and-sandbox" in argv, (
            "Expected bypass flag in codex argv; without it bwrap's unshare-net "
            "fails on hosts lacking CAP_NET_ADMIN."
        )
        assert "--sandbox" not in argv, (
            "--sandbox must not be passed: any mode (including danger-full-access) "
            "still invokes bwrap and fails here."
        )
        assert "--full-auto" not in argv, (
            "--full-auto implies --sandbox workspace-write; incompatible with bypass."
        )
        assert "danger-full-access" not in argv, (
            "danger-full-access does NOT skip bwrap; it still fails on unshare-net."
        )


# ---------------------------------------------------------------------------
# extract_diff_new_lines (T-193)
# ---------------------------------------------------------------------------


class TestExtractDiffNewLines:
    def test_single_hunk_added_and_context_lines(self) -> None:
        diff = (
            "diff --git a/src/x.py b/src/x.py\n"
            "--- a/src/x.py\n"
            "+++ b/src/x.py\n"
            "@@ -1,3 +1,5 @@\n"
            " line1\n"
            " line2\n"
            "+added1\n"
            "+added2\n"
            " line3\n"
        )
        lines = extract_diff_new_lines(diff)
        # New side: 1 (line1), 2 (line2), 3 (added1), 4 (added2), 5 (line3)
        assert lines == {"src/x.py": {1, 2, 3, 4, 5}}

    def test_removed_lines_do_not_consume_new_side(self) -> None:
        diff = (
            "diff --git a/src/x.py b/src/x.py\n"
            "--- a/src/x.py\n"
            "+++ b/src/x.py\n"
            "@@ -1,4 +1,3 @@\n"
            " keep\n"
            "-remove1\n"
            "-remove2\n"
            " after\n"
            "+added\n"
        )
        # New side: 1 (keep), 2 (after), 3 (added)
        assert extract_diff_new_lines(diff) == {"src/x.py": {1, 2, 3}}

    def test_multiple_hunks_in_same_file(self) -> None:
        diff = (
            "diff --git a/src/x.py b/src/x.py\n"
            "--- a/src/x.py\n"
            "+++ b/src/x.py\n"
            "@@ -1,2 +1,2 @@\n"
            " a\n"
            "+b\n"
            "@@ -10,2 +11,3 @@\n"
            " x\n"
            "+y\n"
            " z\n"
        )
        lines = extract_diff_new_lines(diff)
        assert lines == {"src/x.py": {1, 2, 11, 12, 13}}

    def test_multiple_files(self) -> None:
        diff = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+b\n"
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -5 +5,2 @@\n"
            " x\n"
            "+y\n"
        )
        lines = extract_diff_new_lines(diff)
        assert lines == {"a.py": {1}, "b.py": {5, 6}}

    def test_empty_diff_returns_empty_dict(self) -> None:
        assert extract_diff_new_lines("") == {}

    def test_no_newline_marker_is_ignored(self) -> None:
        diff = (
            "diff --git a/x b/x\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+b\n"
            "\\ No newline at end of file\n"
        )
        # Only line 1 (the added +b) is on the new side
        assert extract_diff_new_lines(diff) == {"x": {1}}


# ---------------------------------------------------------------------------
# _partition_findings + _format_review_body (T-193)
# ---------------------------------------------------------------------------


class TestPartitionFindings:
    def test_inline_kept_when_line_is_in_diff(self) -> None:
        result = ReviewResult(
            verdict="comment",
            summary="s",
            findings=[
                ReviewFinding(file="src/x.py", line=3, severity="high", body="bug here"),
            ],
        )
        inline, orphans = _partition_findings(result, {"src/x.py": {1, 2, 3}})
        assert len(inline) == 1
        assert inline[0]["path"] == "src/x.py"
        assert inline[0]["line"] == 3
        assert inline[0]["side"] == "RIGHT"
        assert "[HIGH]" in inline[0]["body"]
        assert orphans == []

    def test_finding_not_in_diff_becomes_orphan(self) -> None:
        result = ReviewResult(
            verdict="comment",
            summary="s",
            findings=[
                ReviewFinding(file="src/x.py", line=99, severity="low", body="nope"),
            ],
        )
        inline, orphans = _partition_findings(result, {"src/x.py": {1, 2}})
        assert inline == []
        assert len(orphans) == 1
        assert orphans[0].line == 99

    def test_finding_for_unknown_file_becomes_orphan(self) -> None:
        result = ReviewResult(
            verdict="comment",
            summary="s",
            findings=[
                ReviewFinding(file="src/other.py", line=1, severity="medium", body="x"),
            ],
        )
        inline, orphans = _partition_findings(result, {"src/x.py": {1}})
        assert inline == []
        assert len(orphans) == 1


class TestFormatReviewBody:
    def test_summary_only(self) -> None:
        result = ReviewResult(verdict="approve", summary="LGTM", findings=[])
        body = _format_review_body(result, [])
        assert "LGTM" in body
        assert "Findings not attached" not in body

    def test_includes_orphans_section(self) -> None:
        result = ReviewResult(verdict="comment", summary="see below", findings=[])
        orphans = [
            ReviewFinding(file="a.py", line=99, severity="high", body="out of diff"),
        ]
        body = _format_review_body(result, orphans)
        assert "Findings not attached to a diff line" in body
        assert "`a.py:99`" in body
        assert "[HIGH]" in body


# ---------------------------------------------------------------------------
# post_review (T-193)
# ---------------------------------------------------------------------------


_SAMPLE_DIFF_WITH_LINE = (
    "diff --git a/src/x.py b/src/x.py\n"
    "--- a/src/x.py\n"
    "+++ b/src/x.py\n"
    "@@ -1,2 +1,2 @@\n"
    "-old\n"
    "+new\n"
    " context\n"
)


class TestPostReview:
    @pytest.mark.asyncio
    async def test_success_posts_correct_payload(self) -> None:
        result = ReviewResult(
            verdict="request_changes",
            summary="has issues",
            findings=[
                ReviewFinding(file="src/x.py", line=1, severity="high", body="bad"),
            ],
        )
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock() as mock:
            route = mock.post(url).mock(return_value=httpx.Response(200, json={"id": 1}))
            ok = await post_review(
                "sachinkundu/cloglog", 42, result, _SAMPLE_DIFF_WITH_LINE, "ghs_test"
            )

        assert ok is True
        assert route.call_count == 1
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer ghs_test"
        assert req.headers["Accept"] == "application/vnd.github+json"
        assert req.headers["X-GitHub-Api-Version"] == "2022-11-28"
        payload = json.loads(req.content)
        # Even for verdict="request_changes", the event is always COMMENT
        # (human is the only one allowed to approve / request changes).
        assert payload["event"] == "COMMENT"
        assert "has issues" in payload["body"]
        assert len(payload["comments"]) == 1
        assert payload["comments"][0]["path"] == "src/x.py"
        assert payload["comments"][0]["line"] == 1
        assert payload["comments"][0]["side"] == "RIGHT"
        assert "[HIGH]" in payload["comments"][0]["body"]

    @pytest.mark.asyncio
    async def test_orphan_findings_fall_back_to_body(self) -> None:
        result = ReviewResult(
            verdict="comment",
            summary="see body",
            findings=[
                ReviewFinding(file="src/x.py", line=99, severity="low", body="not in diff"),
            ],
        )
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock() as mock:
            route = mock.post(url).mock(return_value=httpx.Response(200, json={"id": 1}))
            ok = await post_review(
                "sachinkundu/cloglog", 42, result, _SAMPLE_DIFF_WITH_LINE, "ghs_test"
            )

        assert ok is True
        payload = json.loads(route.calls.last.request.content)
        assert payload["comments"] == []  # orphan, not inline
        assert "src/x.py:99" in payload["body"]

    @pytest.mark.asyncio
    async def test_retry_then_success(self) -> None:
        result = ReviewResult(verdict="approve", summary="fine", findings=[])
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with (
            respx.mock() as mock,
            patch("src.gateway.review_engine.REVIEW_POST_RETRY_DELAY_SECONDS", 0.0),
        ):
            route = mock.post(url).mock(
                side_effect=[
                    httpx.Response(502, json={"message": "bad gateway"}),
                    httpx.Response(200, json={"id": 1}),
                ]
            )
            ok = await post_review(
                "sachinkundu/cloglog", 42, result, _SAMPLE_DIFF_WITH_LINE, "ghs_test"
            )

        assert ok is True
        assert route.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_then_fail_returns_false(self) -> None:
        result = ReviewResult(verdict="approve", summary="fine", findings=[])
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with (
            respx.mock() as mock,
            patch("src.gateway.review_engine.REVIEW_POST_RETRY_DELAY_SECONDS", 0.0),
        ):
            route = mock.post(url).mock(return_value=httpx.Response(500, json={"message": "boom"}))
            ok = await post_review(
                "sachinkundu/cloglog", 42, result, _SAMPLE_DIFF_WITH_LINE, "ghs_test"
            )

        assert ok is False
        assert route.call_count == 2  # original + one retry

    @pytest.mark.asyncio
    async def test_verdict_never_becomes_approve_or_request_changes(self) -> None:
        """Every verdict lands as COMMENT — only humans flip merge state."""
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        for verdict in ("approve", "request_changes", "comment"):
            result = ReviewResult(verdict=verdict, summary="x", findings=[])
            with respx.mock() as mock:
                route = mock.post(url).mock(return_value=httpx.Response(200, json={"id": 1}))
                await post_review("sachinkundu/cloglog", 42, result, _SAMPLE_DIFF_WITH_LINE, "t")
                payload = json.loads(route.calls.last.request.content)
                assert payload["event"] == "COMMENT"


# ---------------------------------------------------------------------------
# Integration test — full flow with subprocess and GitHub both mocked (T-193)
# ---------------------------------------------------------------------------


class TestFullFlowIntegration:
    @pytest.fixture(autouse=True)
    def _stub_count_bot_reviews(self) -> Any:
        with patch(
            "src.gateway.review_engine.count_bot_reviews",
            new=AsyncMock(return_value=0),
        ) as m:
            yield m

    @pytest.mark.asyncio
    async def test_webhook_to_posted_review(self) -> None:
        """Walk a PR_OPENED event through the consumer and out to the reviews API.

        Both ends (gh pr diff, review agent subprocess, GitHub reviews API)
        are stubbed. The assertion is that, given a valid flow, the consumer
        fires exactly one HTTP POST with the right payload shape.
        """
        consumer = ReviewEngineConsumer(max_per_hour=10)
        pr_diff = (
            "diff --git a/src/x.py b/src/x.py\n"
            "--- a/src/x.py\n"
            "+++ b/src/x.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
        )
        review_json = json.dumps(
            {
                "verdict": "comment",
                "summary": "one small thing",
                "findings": [
                    {
                        "file": "src/x.py",
                        "line": 1,
                        "severity": "medium",
                        "body": "rename please",
                    }
                ],
            }
        )

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=pr_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            # Find -o flag to get output path and write review JSON there
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(review_json)
                    break
            return _FakeProcess(returncode=0)

        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            respx.mock() as mock,
        ):
            route = mock.post(url).mock(return_value=httpx.Response(200, json={"id": 1}))
            await consumer.handle(_event())

        assert route.call_count == 1
        payload = json.loads(route.calls.last.request.content)
        assert payload["event"] == "COMMENT"
        assert len(payload["comments"]) == 1
        assert payload["comments"][0]["path"] == "src/x.py"
        assert payload["comments"][0]["line"] == 1


# ---------------------------------------------------------------------------
# count_bot_reviews + 2-cycle cap (T-193 follow-up)
# ---------------------------------------------------------------------------


class TestCountBotReviews:
    @pytest.mark.asyncio
    async def test_counts_only_codex_bot_reviews(self) -> None:
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            {"user": {"login": _CODEX_BOT}, "state": "COMMENTED"},
            {"user": {"login": "sachinkundu"}, "state": "COMMENTED"},
            {"user": {"login": _CODEX_BOT}, "state": "COMMENTED"},
            {"user": {"login": _CLAUDE_BOT}, "state": "COMMENTED"},
            {"user": {"login": "someone-else"}, "state": "APPROVED"},
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            n = await count_bot_reviews("sachinkundu/cloglog", 42, "t")
        # Only counts Codex bot reviews, not Claude bot
        assert n == 2

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_reviews(self) -> None:
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=[]))
            n = await count_bot_reviews("sachinkundu/cloglog", 42, "t")
        assert n == 0

    @pytest.mark.asyncio
    async def test_tolerates_missing_user_key(self) -> None:
        """GitHub occasionally omits ``user`` on dismissed reviews; don't explode."""
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock() as mock:
            mock.get(url).mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        {"state": "DISMISSED"},  # no user
                        {"user": None, "state": "DISMISSED"},
                        {"user": {"login": _CODEX_BOT}, "state": "COMMENTED"},
                    ],
                )
            )
            n = await count_bot_reviews("sachinkundu/cloglog", 42, "t")
        assert n == 1


class TestTwoCycleCap:
    @pytest.mark.asyncio
    async def test_skips_agent_when_bot_already_reviewed_max(self, sample_diff: str) -> None:
        """Having MAX_REVIEWS_PER_PR or more prior bot reviews short-circuits."""
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            pytest.fail("No subprocess should launch when the cap is already reached")

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=MAX_REVIEWS_PER_PR),
            ),
        ):
            await consumer.handle(_event())

    @pytest.mark.asyncio
    async def test_proceeds_when_under_cap(self, sample_diff: str) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)
        launched: list[tuple[str, ...]] = []

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            launched.append(argv)
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        codex_launched = []

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            codex_launched.append(args)
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(
                        json.dumps({"verdict": "approve", "summary": "", "findings": []})
                    )
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=MAX_REVIEWS_PER_PR - 1),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ),
        ):
            await consumer.handle(_event())

        # gh pr diff via _spawn, codex via create_subprocess_exec
        assert len(launched) == 1
        assert len(codex_launched) == 1


# ---------------------------------------------------------------------------
# TestReviewSourceRoot (T-255)
# ---------------------------------------------------------------------------


def _make_happy_path_mocks(sample_diff: str, sample_review_json: str):
    """Return (fake_spawn, fake_create, captured_argv_list, captured_kwargs_list).

    fake_spawn handles 'gh pr diff'.
    fake_create writes the review JSON to the -o output path and captures argv/kwargs.
    """
    captured: list[tuple[str, ...]] = []
    captured_kwargs: list[dict[str, Any]] = []

    async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
        if argv[0] == "gh":
            return _FakeProcess(stdout=sample_diff.encode())
        pytest.fail("_spawn should only be called for gh")

    async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
        captured.append(args)
        captured_kwargs.append(kwargs)
        for i, arg in enumerate(args):
            if arg == "-o" and i + 1 < len(args):
                Path(args[i + 1]).write_text(sample_review_json)
                break
        return _FakeProcess(returncode=0)

    return _fake_spawn, _fake_create, captured, captured_kwargs


class TestReviewSourceRoot:
    """Tests for T-255: project_root from settings.review_source_root, not Path.cwd()."""

    @pytest.fixture(autouse=True)
    def _stub_count_bot_reviews(self) -> Any:
        with patch(
            "src.gateway.review_engine.count_bot_reviews",
            new=AsyncMock(return_value=0),
        ) as m:
            yield m

    # ------------------------------------------------------------------
    # 1. resolve_review_source_root() unit tests (no subprocess needed)
    # ------------------------------------------------------------------

    def test_resolve_returns_setting_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root", Path("/tmp/fake-main")
        )
        assert resolve_review_source_root() == Path("/tmp/fake-main")

    def test_resolve_falls_back_to_cwd_when_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.gateway.review_engine.settings.review_source_root", None)
        assert resolve_review_source_root() == Path.cwd()

    # ------------------------------------------------------------------
    # 2. _run_review_agent uses settings.review_source_root for -C and cwd=
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_project_root_from_setting(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_diff: str,
        sample_review_json: str,
    ) -> None:
        """When review_source_root is set, -C and cwd= must use that path."""
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            Path("/tmp/fake-main"),
        )
        consumer = ReviewEngineConsumer(max_per_hour=10)
        fake_spawn, fake_create, captured, captured_kwargs = _make_happy_path_mocks(
            sample_diff, sample_review_json
        )

        with (
            patch("src.gateway.review_engine._spawn", side_effect=fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ),
        ):
            await consumer.handle(_event())

        assert len(captured) == 1, "codex must be invoked exactly once"
        argv = captured[0]
        assert "-C" in argv, "-C flag missing from codex argv"
        c_idx = argv.index("-C")
        assert argv[c_idx + 1] == "/tmp/fake-main", (
            f"Expected -C /tmp/fake-main, got {argv[c_idx + 1]!r}"
        )
        assert captured_kwargs[0].get("cwd") == "/tmp/fake-main", (
            f"Expected cwd='/tmp/fake-main', got {captured_kwargs[0].get('cwd')!r}"
        )

    @pytest.mark.asyncio
    async def test_project_root_falls_back_to_cwd_when_setting_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_diff: str,
        sample_review_json: str,
    ) -> None:
        """When review_source_root is None, -C and cwd= must equal Path.cwd()."""
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            None,
        )
        consumer = ReviewEngineConsumer(max_per_hour=10)
        fake_spawn, fake_create, captured, captured_kwargs = _make_happy_path_mocks(
            sample_diff, sample_review_json
        )

        with (
            patch("src.gateway.review_engine._spawn", side_effect=fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ),
        ):
            await consumer.handle(_event())

        assert len(captured) == 1
        argv = captured[0]
        assert "-C" in argv
        c_idx = argv.index("-C")
        assert argv[c_idx + 1] == str(Path.cwd()), (
            f"Expected -C {Path.cwd()!s}, got {argv[c_idx + 1]!r}"
        )
        assert captured_kwargs[0].get("cwd") == str(Path.cwd()), (
            f"Expected cwd={Path.cwd()!s}, got {captured_kwargs[0].get('cwd')!r}"
        )

    # ------------------------------------------------------------------
    # 3. Regression guard: -C is always present in argv
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dash_c_always_in_codex_argv(
        self,
        monkeypatch: pytest.MonkeyPatch,
        sample_diff: str,
        sample_review_json: str,
    ) -> None:
        """Regression guard — dropping -C must cause this test to fail loudly."""
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            None,
        )
        consumer = ReviewEngineConsumer(max_per_hour=10)
        fake_spawn, fake_create, captured, _ = _make_happy_path_mocks(
            sample_diff, sample_review_json
        )

        with (
            patch("src.gateway.review_engine._spawn", side_effect=fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=fake_create),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ),
        ):
            await consumer.handle(_event())

        assert len(captured) == 1
        assert "-C" in captured[0], (
            "-C flag not found in codex argv — a future refactor dropped it. "
            "Restore -C <project_root> to ensure codex reads from the correct git checkout."
        )

    # ------------------------------------------------------------------
    # 4. log_review_source_root with bogus path — must not raise
    # ------------------------------------------------------------------

    def test_log_review_source_root_bogus_path_no_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A nonexistent path must not raise; an info record must still be emitted."""
        import logging

        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            Path("/nonexistent/does/not/exist"),
        )
        test_logger = logging.getLogger("src.gateway.review_engine")
        with caplog.at_level("INFO", logger="src.gateway.review_engine"):
            # Must not raise even though git will fail or the path doesn't exist
            log_review_source_root(test_logger)

        assert any("Review source root" in r.message for r in caplog.records), (
            "Expected an info record containing 'Review source root'"
        )

    # ------------------------------------------------------------------
    # 5. log_review_source_root on a real git directory — SHA in log
    # ------------------------------------------------------------------

    def test_log_review_source_root_real_git_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When pointed at a real git repo, the log line must contain a 40-char hex SHA."""
        import logging

        repo_root = Path.cwd()  # pytest runs from repo root, which is a git repo
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            repo_root,
        )
        test_logger = logging.getLogger("src.gateway.review_engine")
        with caplog.at_level("INFO", logger="src.gateway.review_engine"):
            log_review_source_root(test_logger)

        info_records = [
            r for r in caplog.records if r.levelname == "INFO" and "Review source root" in r.message
        ]
        assert info_records, "Expected at least one INFO record with 'Review source root'"
        message = info_records[0].message
        assert str(repo_root) in message, (
            f"Expected the repo root path {repo_root!s} in the log message, got: {message!r}"
        )
        sha_match = re.search(r"\b[0-9a-f]{40}\b", message)
        assert sha_match is not None, (
            f"Expected a 40-char hex SHA in the log message, got: {message!r}"
        )
