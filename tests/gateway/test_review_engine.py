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
import uuid
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
    _should_skip_for_cap,
    count_bot_reviews,
    extract_diff_new_lines,
    filter_diff,
    is_review_agent_available,
    latest_codex_review_is_approval,
    log_review_source_root,
    parse_review_output,
    post_review,
    resolve_pr_review_root,
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

    def test_drops_docs_demos_demo_md_only(self) -> None:
        """T-275: ONLY the showboat-rendered ``demo.md`` is filtered; helper
        scripts (``demo-script.sh``, ``proof_*.py``) still reach codex because
        they ARE code that ``make demo`` / ``make quality`` actually execute.

        The original T-275 shipped a broader ``docs/demos/`` filter; codex on
        PR #197 round 2 flagged it HIGH because it hid real executable code
        from review. This test pins the narrower regex.
        """
        diff = (
            self._section("docs/demos/wt-foo/demo.md")
            + "\n"
            + self._section("docs/demos/wt-foo/demo-script.sh")
            + "\n"
            + self._section("docs/demos/wt-foo/proof_filter_diff.py")
            + "\n"
            + self._section("docs/demos/wt-foo/T-123/demo.md")
            + "\n"
            + self._section("src/gateway/review_engine.py")
        )
        out = filter_diff(diff)
        # Byte-exact proof outputs — filtered.
        assert "docs/demos/wt-foo/demo.md" not in out
        assert "docs/demos/wt-foo/T-123/demo.md" not in out
        # Helper scripts under docs/demos/ — MUST survive for codex review.
        assert "docs/demos/wt-foo/demo-script.sh" in out
        assert "docs/demos/wt-foo/proof_filter_diff.py" in out
        # Unrelated source file survives.
        assert "src/gateway/review_engine.py" in out


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


class _FakeStream:
    """Minimal StreamReader stand-in — exposes ``read()`` returning preset bytes."""

    def __init__(self, data: bytes = b"") -> None:
        self._data = data
        self.read_calls = 0

    async def read(self, n: int = -1) -> bytes:
        self.read_calls += 1
        out = self._data
        self._data = b""  # drain once
        return out


class _FakeProcess:
    """Minimal stand-in for an ``asyncio.subprocess.Process`` used in tests."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        hang: bool = False,
        stderr_after_kill: bytes | None = None,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang
        self.kill_calls = 0
        # `stderr` stream exposes whatever the kernel buffered before kill.
        # Default: the same bytes ``communicate()`` would have returned.
        tail = stderr_after_kill if stderr_after_kill is not None else stderr
        self.stderr: _FakeStream | None = _FakeStream(tail)

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
        # Cancel the T-381 retry task so it does not drag the test suite.
        for task in list(consumer._pending_retries.values()):
            task.cancel()

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
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_BASE_SECONDS", 0.01),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_CAP_SECONDS", 0.01),
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
# T-381: rate-limit retry scheduling — the skip comment promises a retry; this
# class pins that the promise is honored by an actual scheduled task that calls
# ``_review_pr`` after the wait window. Removing the schedule call (or letting
# it fail to fire) reproduces the original lie.
# ---------------------------------------------------------------------------


class TestRateLimitRetry:
    @staticmethod
    def _saturate(consumer: ReviewEngineConsumer) -> None:
        """Fill all slots so the next ``handle()`` hits the rate-limit branch.

        Tests use ``max_per_hour=1`` rather than ``max_per_hour=0`` because
        the latter is the documented "permanently rate-limited" mode and no
        longer schedules a retry (see ``test_max_per_hour_zero_does_not_schedule_retry``).
        Pre-filling the single slot is what real production traffic looks
        like when the rate limit fires.
        """
        consumer._rate_limiter.allow()

    @pytest.mark.asyncio
    async def test_handle_schedules_real_retry_task(self) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=1)
        self._saturate(consumer)
        with (
            patch.object(consumer, "_notify_skip", new=AsyncMock()) as notify,
            patch.object(consumer, "_review_pr", new=AsyncMock()),
        ):
            await consumer.handle(_event())

        try:
            notify.assert_called_once()
            key = ("sachinkundu/cloglog", 42)
            assert key in consumer._pending_retries, (
                "rate-limit skip must schedule a retry task — the user-facing "
                "comment promises one (T-381)"
            )
            task = consumer._pending_retries[key]
            assert isinstance(task, asyncio.Task)
            assert not task.done()
        finally:
            for task in list(consumer._pending_retries.values()):
                task.cancel()

    @pytest.mark.asyncio
    async def test_retry_task_invokes_review_pr_after_wait(self) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=1)
        self._saturate(consumer)
        original_sleep = asyncio.sleep
        slept: list[float] = []

        async def fast_sleep(delay: float) -> None:
            slept.append(delay)
            await original_sleep(0)

        review_done = asyncio.Event()

        async def fake_review(event: WebhookEvent) -> None:
            review_done.set()

        with (
            patch.object(consumer, "_notify_skip", new=AsyncMock()),
            patch.object(consumer, "_review_pr", new=AsyncMock(side_effect=fake_review)) as review,
            patch("src.gateway.review_engine.asyncio.sleep", new=fast_sleep),
        ):
            await consumer.handle(_event())
            # Allow the retry task to run.
            await asyncio.wait_for(review_done.wait(), timeout=1.0)

        review.assert_called_once()
        # The scheduled delay must respect the rate-limiter window — a 0-second
        # delay would reproduce the original lie by retrying instantly while
        # the limiter is still saturated. Buffer adds 1s for clock skew.
        assert slept and slept[0] >= 1.0

    @pytest.mark.asyncio
    async def test_second_push_during_window_replaces_pending_retry(self) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=1)
        self._saturate(consumer)
        with (
            patch.object(consumer, "_notify_skip", new=AsyncMock()),
            patch.object(consumer, "_review_pr", new=AsyncMock()),
        ):
            await consumer.handle(_event(pr_number=99))
            first_task = consumer._pending_retries[("sachinkundu/cloglog", 99)]
            await consumer.handle(_event(pr_number=99))
            second_task = consumer._pending_retries[("sachinkundu/cloglog", 99)]
            # Give the cancellation a tick to settle.
            await asyncio.sleep(0)

        try:
            assert first_task is not second_task
            assert first_task.cancelled() or first_task.done()
        finally:
            for task in list(consumer._pending_retries.values()):
                task.cancel()

    @pytest.mark.asyncio
    async def test_max_per_hour_zero_does_not_schedule_retry(self) -> None:
        """Permanent rate-limit (``max_per_hour=0``) must not schedule a retry.

        Pin for codex review HIGH/MEDIUM-2 (PR #309): T-381 originally
        scheduled a retry on every rate-limit hit, including the
        permanent-block configuration documented at ``docs/review-engine-e2e.md``
        and ``RateLimiter.seconds_until_next_slot``. That contradicted the
        operator's "always rate-limited" intent — a retry would fire ~1s
        after the skip comment. ``wait_seconds == 0.0`` from a False
        ``allow()`` is the unambiguous signal of a permanent block.
        """
        consumer = ReviewEngineConsumer(max_per_hour=0)
        with (
            patch.object(consumer, "_notify_skip", new=AsyncMock()),
            patch.object(consumer, "_review_pr", new=AsyncMock()) as review,
        ):
            await consumer.handle(_event())
            await asyncio.sleep(0)  # let any erroneously-scheduled task tick

        assert consumer._pending_retries == {}, (
            "max_per_hour=0 is the documented permanent-block mode — no retry must be scheduled"
        )
        review.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_retry_reserves_slot_against_other_prs(self) -> None:
        """A pending retry's slot is reserved — unrelated PRs can't claim it.

        Pin for codex review round 2 HIGH (PR #309): without reservations,
        the retry path called ``allow()`` only at wake-time; a different
        PR could steal the reopened slot in the meantime, so two reviews
        ran inside the same hour even though ``max_per_hour=1``.
        """
        consumer = ReviewEngineConsumer(max_per_hour=1)
        self._saturate(consumer)
        with (
            patch.object(consumer, "_notify_skip", new=AsyncMock()),
            patch.object(consumer, "_review_pr", new=AsyncMock()),
        ):
            await consumer.handle(_event(pr_number=42))
        try:
            # PR 42 has reservation. Now age out the original timestamp —
            # the slot would be free if not for the reservation.
            consumer._rate_limiter._timestamps.clear()
            assert consumer._rate_limiter.allow() is False, (
                "A scheduled retry's reservation must hold the slot "
                "against unrelated PRs (codex round 2 HIGH)"
            )
        finally:
            for task in list(consumer._pending_retries.values()):
                task.cancel()

    @pytest.mark.asyncio
    async def test_zero_wait_at_boundary_still_schedules_retry(self) -> None:
        """``wait_seconds == 0.0`` from a boundary slot-just-opened must schedule.

        Pin for codex review round 2 HIGH (PR #309): the previous round's
        guard treated ``wait_seconds == 0.0`` as the permanent-block
        sentinel, but ``seconds_until_next_slot()`` also returns 0.0
        when the oldest timestamp ages out between the ``allow()`` check
        and the wait-seconds read (millisecond-scale clock skew). The
        sentinel must be ``is_permanently_blocked()``, never a numeric
        comparison.
        """
        consumer = ReviewEngineConsumer(max_per_hour=1)
        self._saturate(consumer)
        with (
            patch.object(consumer, "_notify_skip", new=AsyncMock()),
            patch.object(consumer, "_review_pr", new=AsyncMock()),
            # Make seconds_until_next_slot return 0.0 (slot just opened) —
            # but is_permanently_blocked() is still False because max != 0.
            patch.object(
                consumer._rate_limiter,
                "seconds_until_next_slot",
                return_value=0.0,
            ),
        ):
            await consumer.handle(_event(pr_number=77))
        try:
            assert ("sachinkundu/cloglog", 77) in consumer._pending_retries, (
                "wait_seconds=0.0 with max_per_hour>0 means the slot just "
                "opened — must still schedule a retry, not silently drop it"
            )
        finally:
            for task in list(consumer._pending_retries.values()):
                task.cancel()

    @pytest.mark.asyncio
    async def test_concurrent_rate_limited_pushes_arrival_order_wins(self) -> None:
        """Concurrent pushes register retries in webhook arrival order.

        Pin for codex review round 2 MEDIUM (PR #309): registration ran
        AFTER the awaited ``_notify_skip()`` POST, so a slow first POST
        could overwrite a newer event's registration. Now scheduling
        runs synchronously before the await; arrival order wins
        regardless of POST latency.
        """
        consumer = ReviewEngineConsumer(max_per_hour=1)
        self._saturate(consumer)

        first_skip_release = asyncio.Event()
        skip_calls = 0

        async def gated_notify_skip(*args: Any, **kwargs: Any) -> None:
            nonlocal skip_calls
            skip_calls += 1
            # Gate ONLY the first call so the second handle() can run
            # synchronously past its own (ungated) notify_skip and
            # complete before the first releases.
            if skip_calls == 1:
                await first_skip_release.wait()

        with (
            patch.object(consumer, "_notify_skip", side_effect=gated_notify_skip),
            patch.object(consumer, "_review_pr", new=AsyncMock()),
        ):
            first = asyncio.create_task(consumer.handle(_event(pr_number=11)))
            # Yield so handle() runs synchronously up to the first await
            # (which is _notify_skip — by which point scheduling is done).
            await asyncio.sleep(0)
            first_event_task = consumer._pending_retries[("sachinkundu/cloglog", 11)]

            await consumer.handle(_event(pr_number=11))
            second_event_task = consumer._pending_retries[("sachinkundu/cloglog", 11)]
            assert first_event_task is not second_event_task, (
                "Second push must replace the first's pending retry (arrival order wins)"
            )

            first_skip_release.set()
            await first
            # First handle() finishes its POST after the second already
            # registered — the pending entry must still be the second's,
            # never overwritten by the slow first.
            assert consumer._pending_retries[("sachinkundu/cloglog", 11)] is second_event_task, (
                "Slow POST on the first event must not retroactively "
                "overwrite the second event's registration "
                "(codex round 2 MEDIUM)"
            )

        for task in list(consumer._pending_retries.values()):
            task.cancel()


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

    def test_approve_with_critical_finding_is_demoted_to_warning(self) -> None:
        """Contradictory approve (verdict=approve + [CRITICAL] finding) must NOT
        emit `:pass:`. Mirrors ``ReviewLoop._reached_consensus``'s refusal to
        short-circuit; aligns the GitHub body with real consensus state so the
        T-227 approval helper can't be fooled (PR #201 round 2 HIGH)."""
        result = ReviewResult(
            verdict="approve",
            summary="patch is correct",
            findings=[
                ReviewFinding(file="a.py", line=1, severity="critical", body="oops"),
            ],
        )
        body = _format_review_body(result, [])
        assert not body.startswith(":pass:"), (
            "verdict=approve + severe finding must not emit :pass: — "
            "latest_codex_review_is_approval would treat it as a real approval."
        )
        assert body.startswith(":warning:")

    def test_approve_with_high_finding_is_demoted_to_warning(self) -> None:
        """Same rule for [HIGH] as for [CRITICAL]; both are in _SEVERE_SEVERITIES."""
        result = ReviewResult(
            verdict="approve",
            summary="patch is correct",
            findings=[
                ReviewFinding(file="a.py", line=1, severity="high", body="oops"),
            ],
        )
        body = _format_review_body(result, [])
        assert not body.startswith(":pass:")
        assert body.startswith(":warning:")

    def test_approve_with_low_finding_still_emits_pass(self) -> None:
        """Only critical/high demote — low/medium/info are compatible with approval."""
        result = ReviewResult(
            verdict="approve",
            summary="nitpick",
            findings=[
                ReviewFinding(file="a.py", line=1, severity="low", body="style"),
                ReviewFinding(file="a.py", line=2, severity="medium", body="trivial"),
                ReviewFinding(file="a.py", line=3, severity="info", body="fyi"),
            ],
        )
        body = _format_review_body(result, [])
        assert body.startswith(":pass:")


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

    @pytest.mark.asyncio
    async def test_commit_id_included_when_head_sha_provided(self) -> None:
        """commit_id in payload pins the review to the SHA codex actually read."""
        result = ReviewResult(verdict="comment", summary="ok", findings=[])
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock() as mock:
            route = mock.post(url).mock(return_value=httpx.Response(200, json={"id": 1}))
            ok = await post_review(
                "sachinkundu/cloglog",
                42,
                result,
                _SAMPLE_DIFF_WITH_LINE,
                "ghs_test",
                head_sha="abc1234def5678901234567890123456789012ab",
            )
        assert ok is True
        payload = json.loads(route.calls.last.request.content)
        assert payload["commit_id"] == "abc1234def5678901234567890123456789012ab"

    @pytest.mark.asyncio
    async def test_commit_id_omitted_when_head_sha_empty(self) -> None:
        """Graceful degradation: empty head_sha falls back to GitHub's default stamping."""
        result = ReviewResult(verdict="comment", summary="ok", findings=[])
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock() as mock:
            route = mock.post(url).mock(return_value=httpx.Response(200, json={"id": 1}))
            ok = await post_review(
                "sachinkundu/cloglog",
                42,
                result,
                _SAMPLE_DIFF_WITH_LINE,
                "ghs_test",
                head_sha="",
            )
        assert ok is True
        payload = json.loads(route.calls.last.request.content)
        assert "commit_id" not in payload


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

    @pytest.mark.asyncio
    async def test_degraded_path_includes_commit_id(self) -> None:
        """Degraded path (session_factory=None) must forward head_sha as commit_id.

        Regression pin for T-365: the single-turn fallback branch in
        ReviewEngineConsumer._review_pr() was the one code path that still
        called post_review() without head_sha after the main fix landed.
        """
        consumer = ReviewEngineConsumer(max_per_hour=10)  # session_factory=None → degraded path
        pr_diff = (
            "diff --git a/src/x.py b/src/x.py\n"
            "--- a/src/x.py\n"
            "+++ b/src/x.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
        )
        review_json = json.dumps({"verdict": "comment", "summary": "ok", "findings": []})

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=pr_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(review_json)
                    break
            return _FakeProcess(returncode=0)

        sha = "1a07b401deadbeefcafe1234567890abcdef5678"
        event = _event()
        # Inject a pull_request.head.sha so the consumer resolves head_sha
        event = WebhookEvent(
            type=event.type,
            delivery_id=event.delivery_id,
            repo_full_name=event.repo_full_name,
            pr_number=event.pr_number,
            pr_url=event.pr_url,
            head_branch=event.head_branch,
            base_branch=event.base_branch,
            sender=event.sender,
            raw={"pull_request": {"head": {"sha": sha}}},
        )

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
            await consumer.handle(event)

        assert route.call_count == 1
        payload = json.loads(route.calls.last.request.content)
        assert payload.get("commit_id") == sha, (
            "Degraded path must forward head_sha as commit_id — "
            "without it, latest_codex_review_is_approval() filters the review out "
            "and count_bot_reviews double-counts sessions against the 5-session cap."
        )


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


class TestShouldSkipForCap:
    """Pure decision-helper unit tests (T-227).

    The helper collapses the verdict-based + backstop cap logic into a
    total function so integration tests don't have to re-simulate it and
    demos can call it in-process. Exercised from three callers: the
    cap-check in ``_review_pr``, these tests, and the T-227 demo.
    """

    def test_proceeds_under_backstop_with_no_approval(self) -> None:
        # Below backstop AND no approval → proceed.
        assert _should_skip_for_cap(0, False) == (False, False)
        assert _should_skip_for_cap(1, False) == (False, False)
        assert _should_skip_for_cap(MAX_REVIEWS_PER_PR - 1, False) == (False, False)

    def test_silent_skip_when_latest_is_approval(self) -> None:
        # Latest bot review emitted `:pass:` — silent skip, no backstop comment.
        # Author already has the approval signal.
        assert _should_skip_for_cap(1, True) == (True, False)
        assert _should_skip_for_cap(MAX_REVIEWS_PER_PR - 1, True) == (True, False)

    def test_backstop_triggers_at_cap_without_approval(self) -> None:
        # At or above the backstop with no approval → skip WITH comment.
        assert _should_skip_for_cap(MAX_REVIEWS_PER_PR, False) == (True, True)
        assert _should_skip_for_cap(MAX_REVIEWS_PER_PR + 1, False) == (True, True)

    def test_approval_beats_backstop(self) -> None:
        # If both approval and backstop are true, approval wins — posting
        # a "maximum reached" comment on an already-approved PR is noise.
        assert _should_skip_for_cap(MAX_REVIEWS_PER_PR, True) == (True, False)
        assert _should_skip_for_cap(MAX_REVIEWS_PER_PR + 5, True) == (True, False)

    def test_backstop_value_is_five(self) -> None:
        # T-227: pin the backstop at 5 so a bump needs a deliberate edit.
        assert MAX_REVIEWS_PER_PR == 5


class TestLatestCodexReviewIsApproval:
    """HTTP-integration tests for the approval-detection helper (T-227).

    ``:pass:`` is the body prefix ``_format_review_body`` emits when codex
    returns ``verdict="approve"``. The bot never posts with
    ``event="APPROVE"`` (pinned by ``test_verdict_never_becomes_approve_or_request_changes``),
    so body-prefix detection is the canonical approval signal on GitHub.

    Scoping is per-``head_sha``: an approval of commit A must not suppress
    review of a newly-pushed commit B. Rows are filtered by
    ``commit_id == head_sha`` before the latest-row check.
    """

    _SHA_A = "a" * 40
    _SHA_B = "b" * 40

    @pytest.mark.asyncio
    async def test_returns_true_when_latest_codex_body_starts_with_pass(self) -> None:
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": ":warning: found an issue",
            },
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": ":pass: looks good, all addressed",
            },
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_A
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_latest_codex_body_is_warning(self) -> None:
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": ":pass: earlier turn looked clean",
            },
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": ":warning: but this turn spotted X",
            },
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_A
            )
        # Latest turn on this head is `:warning:`, so the earlier `:pass:` does
        # NOT count — a later turn on the same commit that flipped verdict
        # reopens the review window.
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_no_codex_reviews(self) -> None:
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=[]))
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_A
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_ignores_non_codex_bot_reviews(self) -> None:
        """Human or claude-bot ``:pass:``-looking bodies must not count as bot approval."""
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            {
                "user": {"login": "sachinkundu"},
                "commit_id": self._SHA_A,
                "body": ":pass: LGTM",
            },
            {
                "user": {"login": _CLAUDE_BOT},
                "commit_id": self._SHA_A,
                "body": ":pass: pushed fix",
            },
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": ":warning: still has issues",
            },
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_A
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_tolerates_missing_body_and_missing_user(self) -> None:
        """Dismissed/malformed rows never crash — missing body just fails the prefix test."""
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            {"state": "DISMISSED"},  # no user, no body, no commit_id
            {"user": None, "state": "DISMISSED"},
            {"user": {"login": _CODEX_BOT}, "commit_id": self._SHA_A},  # no body
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_A
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_approval_on_older_sha_does_not_apply_to_new_sha(self) -> None:
        """Regression guard (codex PR #201 round 1 MEDIUM): approval of commit
        A must NOT suppress review of a newly-pushed commit B. Aligns with the
        review pipeline's per-(pr_url, head_sha, stage) consensus scope."""
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            # Prior turns on commit A, concluding with :pass:
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": ":warning: found an issue",
            },
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": ":pass: looks good",
            },
            # No reviews yet on commit B.
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            # The webhook is asking about head_sha=B. A's approval must not leak.
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_B
            )
        assert result is False, (
            "Approval of an earlier commit must not suppress review of a newer "
            "commit — per-head_sha semantics align with review_loop consensus scope."
        )

    @pytest.mark.asyncio
    async def test_returns_false_when_head_sha_is_empty(self) -> None:
        """No HTTP call is made when head_sha is empty — caller couldn't scope."""
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(url).mock(return_value=httpx.Response(200, json=[]))
            result = await latest_codex_review_is_approval("sachinkundu/cloglog", 42, "t", "")
        assert result is False
        assert route.call_count == 0, "Empty head_sha must short-circuit before any HTTP"

    @pytest.mark.asyncio
    async def test_legacy_rows_without_commit_id_are_excluded(self) -> None:
        """Rows missing ``commit_id`` cannot prove approval of a specific commit."""
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            # Legacy row without commit_id, body says :pass:
            {"user": {"login": _CODEX_BOT}, "body": ":pass: legacy approval"},
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_A
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_contradictory_approve_body_is_not_detected_as_approval(self) -> None:
        """Full-path regression guard (PR #201 round 2 HIGH): an approve verdict
        contradicted by a severe finding must reach GitHub with a non-``:pass:``
        body thanks to ``_format_review_body``'s demotion, so this helper
        correctly returns False on webhook replay of that row."""
        # Build the body the way post_review actually builds it — format the
        # ReviewResult through _format_review_body so we exercise the demotion.
        contradictory = ReviewResult(
            verdict="approve",
            summary="patch looks correct",
            findings=[
                ReviewFinding(file="a.py", line=1, severity="critical", body="bad"),
            ],
        )
        body_as_published = _format_review_body(contradictory, [])
        # Sanity: the demotion rule is the reason this works.
        assert not body_as_published.startswith(":pass:")

        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        reviews_json = [
            {
                "user": {"login": _CODEX_BOT},
                "commit_id": self._SHA_A,
                "body": body_as_published,
            },
        ]
        with respx.mock() as mock:
            mock.get(url).mock(return_value=httpx.Response(200, json=reviews_json))
            result = await latest_codex_review_is_approval(
                "sachinkundu/cloglog", 42, "t", self._SHA_A
            )
        assert result is False, (
            "A contradictory approve must not trigger the approval skip — "
            "ReviewLoop._reached_consensus refuses to short-circuit the same case."
        )


class TestVerdictBasedCap:
    """Integration coverage for T-227 verdict-based stop + backstop=5.

    Replaces the T-193 ``TestTwoCycleCap`` at this file location. The cap is
    now: skip when the latest codex review emitted ``:pass:``; otherwise run
    until ``MAX_REVIEWS_PER_PR=5`` sessions without approval, then skip with
    a comment.
    """

    @pytest.mark.asyncio
    async def test_proceeds_when_under_backstop_and_no_approval(self, sample_diff: str) -> None:
        """Coverage 1: N prior COMMENTED/CHANGES_REQUESTED reviews, N < 5 → proceed."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        launched: list[tuple[str, ...]] = []

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            launched.append(argv)
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        codex_launched: list[tuple[Any, ...]] = []

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
                "src.gateway.review_engine.latest_codex_review_is_approval",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ),
        ):
            await consumer.handle(_event())

        # Review proceeded: one gh diff fetch + one codex subprocess.
        assert len(launched) == 1
        assert len(codex_launched) == 1

    @pytest.mark.asyncio
    async def test_skips_silently_when_latest_bot_review_is_approval(
        self, sample_diff: str
    ) -> None:
        """Coverage 2: latest bot review is `:pass:` → skip, no subprocess, no skip comment."""
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            pytest.fail("No subprocess should launch when the bot has already approved")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            pytest.fail("No codex subprocess should launch on approval skip")

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
                new=AsyncMock(return_value=2),
            ),
            patch(
                "src.gateway.review_engine.latest_codex_review_is_approval",
                new=AsyncMock(return_value=True),
            ),
            respx.mock(assert_all_called=False) as mock,
        ):
            # Route is pre-registered so any accidental skip-comment POST
            # lands here; the assertion below pins call_count == 0.
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 0, (
            "Silent-skip branch must not post a skip comment — author already has :pass:"
        )

    @pytest.mark.asyncio
    async def test_backstop_triggers_at_max_without_approval(self, sample_diff: str) -> None:
        """Coverage 3: count >= 5 and no approval → backstop skip (no subprocess)."""
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            pytest.fail("No subprocess should launch when the backstop has tripped")

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
            patch(
                "src.gateway.review_engine.latest_codex_review_is_approval",
                new=AsyncMock(return_value=False),
            ),
            respx.mock() as mock,
        ):
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        # Backstop MUST post the skip comment.
        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        body = payload["body"]
        # Coverage 4: body must mention the maximum and the backstop's number
        # so the author knows why review stopped.
        assert str(MAX_REVIEWS_PER_PR) in body
        assert "maximum" in body.lower()
        assert "approval" in body.lower() or "approved" in body.lower()


# ---------------------------------------------------------------------------
# TestT376PostedCountCap — cap counts POSTED reviews, not session attempts
# ---------------------------------------------------------------------------


class TestT376PostedCountCap:
    """T-376 pin: ``MAX_REVIEWS_PER_PR`` keys off
    ``count_posted_codex_sessions`` (registry rows with ``posted_at IS NOT
    NULL``), not GitHub session count. A session that hits a non-post
    terminal (rate-limit skip, codex_unavailable, post_failed) does NOT
    consume the cap.

    Pin test acceptance from the T-376 task spec:
    - 5 sessions, 2 non-post terminals + 3 posts → cap allows 2 more
      sessions until 5 posts land.
    - 5 successful posts → next session refuses (backstop fires).

    These tests exercise the registry-backed path
    (``session_factory != None``). The legacy GitHub-count fallback used
    by the degraded harness is covered by ``TestT227Cap`` above.
    """

    @staticmethod
    def _event() -> WebhookEvent:
        return WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-376",
            repo_full_name="sachinkundu/cloglog",
            pr_number=376,
            pr_url="https://github.com/sachinkundu/cloglog/pull/376",
            head_branch="wt-codex-review-fixes",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": "f" * 40}}},
        )

    @staticmethod
    def _registry_ctx_factory(posted_count: int) -> Any:
        """Return a no-op registry ctx whose ``count_posted_codex_sessions``
        reports ``posted_count``. Other registry calls return MagicMocks /
        empty PriorContext so the rest of the loop can still wire."""
        from unittest.mock import AsyncMock, MagicMock

        from src.review.interfaces import PriorContext

        class _Ctx:
            async def __aenter__(self) -> object:
                mock = MagicMock()
                mock.count_posted_codex_sessions = AsyncMock(return_value=posted_count)
                mock.prior_findings_and_learnings = AsyncMock(
                    return_value=PriorContext(pr_url="", turns=[])
                )
                return mock

            async def __aexit__(self, *exc: object) -> bool:
                return False

        return _Ctx

    @pytest.mark.asyncio
    async def test_three_posts_five_attempts_cap_does_not_fire(self, sample_diff: str) -> None:
        """5 sessions with 2 non-post terminals + 3 posts → registry says
        3 posted → cap allows the 4th attempt to proceed.

        Pre-T-376 the GitHub-side count would also have read 3 here (no
        post = no GitHub review), so this case happened to behave
        correctly — but pinning it ensures the new registry path keeps
        the same semantics rather than regressing to "count attempts."
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=MagicMock(),
        )
        registry_ctx_cls = self._registry_ctx_factory(posted_count=3)
        codex_ran: list[bool] = []

        class _StubLoop:
            def __init__(self, _reviewer: object, **kwargs: object) -> None:
                pass

            async def run(self, **_kwargs: object) -> object:
                codex_ran.append(True)
                return type("Outcome", (), {"turns_used": 1, "errors": []})()

        with (
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.review_engine.latest_codex_review_is_approval",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "src.gateway.review_engine._create_review_checkout",
                new=AsyncMock(return_value=None),
            ),
            patch("src.gateway.review_loop.CodexReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.ReviewLoop", new=_StubLoop),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value=sample_diff)),
            patch.object(
                consumer,
                "_resolve_project_id",
                new=AsyncMock(return_value=uuid.uuid4()),
            ),
            patch.object(consumer, "_registry", new=lambda: registry_ctx_cls()),
            patch.object(
                consumer,
                "_worktree_query",
                new=lambda: TestOpencodeEnabledFlag._NoopWorktreeQueryCtx(),
            ),
        ):
            await consumer._review_pr(self._event())

        assert codex_ran == [True], (
            "Cap incorrectly tripped at 3 posts (cap=5). T-376 regression: "
            "registry's count_posted_codex_sessions returned 3 — should proceed."
        )

    @pytest.mark.asyncio
    async def test_five_posts_blocks_sixth_session(self, sample_diff: str) -> None:
        """5 successful posts → cap fires, no codex run, skip comment posted."""
        from unittest.mock import AsyncMock, MagicMock, patch

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=MagicMock(),
        )
        registry_ctx_cls = self._registry_ctx_factory(posted_count=5)
        codex_ran: list[bool] = []

        class _StubLoop:
            def __init__(self, _reviewer: object, **kwargs: object) -> None:
                pass

            async def run(self, **_kwargs: object) -> object:
                codex_ran.append(True)
                return type("Outcome", (), {"turns_used": 1, "errors": []})()

        notify_calls: list[Any] = []

        async def _capture_notify(event: Any, reason: Any, body: str) -> None:
            notify_calls.append((reason, body))

        with (
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.review_engine.latest_codex_review_is_approval",
                new=AsyncMock(return_value=False),
            ),
            patch("src.gateway.review_loop.CodexReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.ReviewLoop", new=_StubLoop),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value=sample_diff)),
            patch.object(
                consumer,
                "_resolve_project_id",
                new=AsyncMock(return_value=uuid.uuid4()),
            ),
            patch.object(consumer, "_registry", new=lambda: registry_ctx_cls()),
            patch.object(
                consumer,
                "_worktree_query",
                new=lambda: TestOpencodeEnabledFlag._NoopWorktreeQueryCtx(),
            ),
            patch.object(consumer, "_notify_skip", new=_capture_notify),
        ):
            await consumer._review_pr(self._event())

        assert codex_ran == [], "Codex must NOT run when registry reports 5 posted sessions"
        assert len(notify_calls) == 1, "Cap-reached must post exactly one skip comment"
        reason, body = notify_calls[0]
        assert reason == SkipReason.MAX_REVIEWS
        assert "5" in body and "maximum" in body.lower()


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


# ---------------------------------------------------------------------------
# T-238: TestPostSkipComment — the helper itself
# ---------------------------------------------------------------------------

from src.gateway.review_skip_comments import (  # noqa: E402
    SkipReason,
    post_skip_comment,
    reset_skip_comment_cache,
)

_ISSUES_COMMENTS_URL = "https://api.github.com/repos/sachinkundu/cloglog/issues/42/comments"
_ISSUES_COMMENTS_URL_43 = "https://api.github.com/repos/sachinkundu/cloglog/issues/43/comments"
_GH_REVIEWS_URL = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"


class TestPostSkipComment:
    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_skip_comment_cache()
        yield
        reset_skip_comment_cache()

    @pytest.mark.asyncio
    async def test_posts_issue_comment_on_first_call(self) -> None:
        """POST fires with correct URL, auth header, API version, and body payload."""
        with respx.mock() as mock:
            route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            ok = await post_skip_comment(
                "sachinkundu/cloglog",
                42,
                SkipReason.RATE_LIMIT,
                "rate limit hit",
                "ghs_tok",
            )

        assert ok is True
        assert route.call_count == 1
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer ghs_tok"
        assert req.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert req.headers["Accept"] == "application/vnd.github+json"
        payload = json.loads(req.content)
        assert payload["body"] == "rate limit hit"

    @pytest.mark.asyncio
    async def test_repeat_same_reason_suppressed_within_window(self) -> None:
        """Second call with same (repo, pr, reason) within window returns False without posting."""
        with respx.mock() as mock:
            route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            ok1 = await post_skip_comment(
                "sachinkundu/cloglog", 42, SkipReason.RATE_LIMIT, "msg", "tok"
            )
            ok2 = await post_skip_comment(
                "sachinkundu/cloglog", 42, SkipReason.RATE_LIMIT, "msg", "tok"
            )

        assert ok1 is True
        assert ok2 is False
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_different_reasons_both_post(self) -> None:
        """Two different reasons for the same (repo, pr) both fire a POST."""
        with respx.mock() as mock:
            route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            ok1 = await post_skip_comment(
                "sachinkundu/cloglog", 42, SkipReason.RATE_LIMIT, "a", "tok"
            )
            ok2 = await post_skip_comment(
                "sachinkundu/cloglog", 42, SkipReason.MAX_REVIEWS, "b", "tok"
            )

        assert ok1 is True
        assert ok2 is True
        assert route.call_count == 2

    @pytest.mark.asyncio
    async def test_different_prs_both_post(self) -> None:
        """Same reason for two different PR numbers both fire a POST."""
        with respx.mock() as mock:
            route42 = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            route43 = mock.post(_ISSUES_COMMENTS_URL_43).mock(
                return_value=httpx.Response(201, json={"id": 2})
            )
            ok1 = await post_skip_comment(
                "sachinkundu/cloglog", 42, SkipReason.RATE_LIMIT, "msg", "tok"
            )
            ok2 = await post_skip_comment(
                "sachinkundu/cloglog", 43, SkipReason.RATE_LIMIT, "msg", "tok"
            )

        assert ok1 is True
        assert ok2 is True
        assert route42.call_count == 1
        assert route43.call_count == 1

    @pytest.mark.asyncio
    async def test_http_error_returns_false_does_not_raise(self) -> None:
        """A 500 from GitHub returns False without bubbling an exception."""
        with respx.mock() as mock:
            mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(500, json={"message": "boom"})
            )
            ok = await post_skip_comment(
                "sachinkundu/cloglog", 42, SkipReason.MAX_REVIEWS, "body", "tok"
            )

        assert ok is False


# ---------------------------------------------------------------------------
# T-238: TestSkipCommentsInHandler — the six wiring points
# ---------------------------------------------------------------------------


class TestSkipCommentsInHandler:
    """Assert each short-circuit site posts a skip comment via the issues endpoint."""

    @pytest.fixture(autouse=True)
    def _auto_setup(self):
        """Token stubs + reset skip cache for every test in this class."""
        reset_skip_comment_cache()
        with (
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
        ):
            yield
        reset_skip_comment_cache()

    @pytest.mark.asyncio
    async def test_rate_limit_posts_skip_comment(self) -> None:
        """max_per_hour=0 triggers rate-limit short-circuit and posts a comment."""
        consumer = ReviewEngineConsumer(max_per_hour=0)
        with respx.mock() as mock:
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        assert "rate limit" in payload["body"].lower()

    @pytest.mark.asyncio
    async def test_max_reviews_cap_posts_skip_comment(self) -> None:
        """Backstop (T-227) at MAX_REVIEWS_PER_PR sessions without approval posts a comment."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        with (
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=MAX_REVIEWS_PER_PR),
            ),
            patch(
                "src.gateway.review_engine.latest_codex_review_is_approval",
                new=AsyncMock(return_value=False),
            ),
            respx.mock() as mock,
        ):
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        body_lower = payload["body"].lower()
        # T-227 body: mentions the numeric backstop AND an approval-adjacent word.
        assert "maximum" in body_lower
        assert str(MAX_REVIEWS_PER_PR) in payload["body"]
        assert "approval" in body_lower or "approved" in body_lower

    @pytest.mark.asyncio
    async def test_empty_filtered_diff_posts_skip_comment(self) -> None:
        """A lockfile-only diff triggers NO_REVIEWABLE_FILES and posts a comment."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        only_lock = (
            "diff --git a/package-lock.json b/package-lock.json\n"
            "--- a/package-lock.json\n"
            "+++ b/package-lock.json\n"
            "@@ -1 +1 @@\n-x\n+y\n"
        )

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=only_lock.encode())
            pytest.fail("_spawn should only be called for gh")

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            respx.mock() as mock,
        ):
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        assert "no reviewable files" in payload["body"].lower()

    @pytest.mark.asyncio
    async def test_oversized_diff_posts_skip_comment(self) -> None:
        """A diff exceeding MAX_DIFF_CHARS triggers DIFF_TOO_LARGE and posts a comment."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        big_body = "x" * (MAX_DIFF_CHARS + 100)
        huge_diff = (
            "diff --git a/src/big.py b/src/big.py\n"
            "--- a/src/big.py\n"
            "+++ b/src/big.py\n"
            f"@@ -1 +1 @@\n-{big_body}\n+{big_body}\n"
        )

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=huge_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            respx.mock() as mock,
        ):
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        assert "too large" in payload["body"].lower()

    @pytest.mark.asyncio
    async def test_unparseable_output_posts_skip_comment(self, sample_diff: str) -> None:
        """Agent exits 1 with bad output triggers AGENT_UNPARSEABLE and posts a comment."""
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
            return _FakeProcess(returncode=1, stderr=b"codex: panic at line 42\n")

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            respx.mock() as mock,
        ):
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        body_lower = payload["body"].lower()
        assert "unparseable" in body_lower
        assert "codex: panic" in payload["body"]

    @pytest.mark.asyncio
    async def test_successful_review_posts_no_skip_comment(
        self, sample_diff: str, sample_review_json: str
    ) -> None:
        """Happy path: reviews endpoint fires, issue-comments endpoint is never called."""
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(sample_review_json)
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            # assert_all_called=False: the comments route must remain un-called —
            # do not let respx fail because the route was never hit.
            respx.mock(assert_all_called=False) as mock,
        ):
            reviews_route = mock.post(_GH_REVIEWS_URL).mock(
                return_value=httpx.Response(200, json={"id": 1})
            )
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 99})
            )
            await consumer.handle(_event())

        assert reviews_route.call_count == 1
        assert comments_route.call_count == 0


# ---------------------------------------------------------------------------
# T-239: TestTimeoutRetryAndProbes — retry logic, stderr capture, probe wiring
# ---------------------------------------------------------------------------


class TestTimeoutRetryAndProbes:
    """Tests for the one-retry timeout path, stderr capture, and health probes."""

    @pytest.fixture(autouse=True)
    def _auto_setup(self):
        reset_skip_comment_cache()
        with (
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
        ):
            yield
        reset_skip_comment_cache()

    @pytest.mark.asyncio
    async def test_first_timeout_retries_then_succeeds(
        self, sample_diff: str, sample_review_json: str
    ) -> None:
        """First subprocess hangs; second attempt succeeds — review posted, no skip comment."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        call_count = 0

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _FakeProcess(hang=True)
            for i, arg in enumerate(args):
                if arg == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(sample_review_json)
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_BASE_SECONDS", 0.01),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_CAP_SECONDS", 0.01),
            patch(
                "src.gateway.review_engine._probe_codex_alive",
                new=AsyncMock(return_value=(True, "codex 0.1.0")),
            ),
            patch(
                "src.gateway.review_engine._probe_github_reachable",
                new=AsyncMock(return_value=(True, "200 ok")),
            ),
            respx.mock(assert_all_called=False) as mock,
        ):
            reviews_route = mock.post(_GH_REVIEWS_URL).mock(
                return_value=httpx.Response(200, json={"id": 1})
            )
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 99})
            )
            await consumer.handle(_event())

        assert reviews_route.call_count == 1
        assert comments_route.call_count == 0
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_second_timeout_posts_skip_comment_with_probe_results(
        self, sample_diff: str
    ) -> None:
        """Both attempts hang — skip comment body contains timed_out, probe results."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        hanging_procs: list[_FakeProcess] = []
        call_count = 0

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            nonlocal call_count
            call_count += 1
            proc = _FakeProcess(hang=True)
            hanging_procs.append(proc)
            return proc

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_BASE_SECONDS", 0.01),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_CAP_SECONDS", 0.01),
            patch(
                "src.gateway.review_engine._probe_codex_alive",
                new=AsyncMock(return_value=(True, "codex 0.1.0")),
            ),
            patch(
                "src.gateway.review_engine._probe_github_reachable",
                new=AsyncMock(return_value=(False, "HTTPError: boom")),
            ),
            respx.mock() as mock,
        ):
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        body = payload["body"]
        assert "timed out" in body.lower()
        assert "codex 0.1.0" in body
        assert "HTTPError" in body
        assert all(p.kill_calls >= 1 for p in hanging_procs)

    @pytest.mark.asyncio
    async def test_timeout_captures_stderr_excerpt(self, sample_diff: str) -> None:
        """Stderr text appears in the skip-comment body after both attempts time out."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        stderr_bytes = b"fatal: stack overflow at line 7\n"

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            return _FakeProcess(hang=True, stderr_after_kill=stderr_bytes)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_BASE_SECONDS", 0.01),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_CAP_SECONDS", 0.01),
            patch(
                "src.gateway.review_engine._probe_codex_alive",
                new=AsyncMock(return_value=(True, "ok")),
            ),
            patch(
                "src.gateway.review_engine._probe_github_reachable",
                new=AsyncMock(return_value=(True, "200 ok")),
            ),
            respx.mock() as mock,
        ):
            comments_route = mock.post(_ISSUES_COMMENTS_URL).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert comments_route.call_count == 1
        payload = json.loads(comments_route.calls.last.request.content)
        assert "stack overflow" in payload["body"]

    @pytest.mark.asyncio
    async def test_structured_log_entry_on_second_timeout(
        self, sample_diff: str, caplog: Any
    ) -> None:
        """Second timeout emits a WARNING starting with 'review_timeout' with all required keys."""
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            return _FakeProcess(hang=True)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_BASE_SECONDS", 0.01),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_CAP_SECONDS", 0.01),
            patch(
                "src.gateway.review_engine._probe_codex_alive",
                new=AsyncMock(return_value=(True, "codex 0.1.0")),
            ),
            patch(
                "src.gateway.review_engine._probe_github_reachable",
                new=AsyncMock(return_value=(False, "HTTPError: unreachable")),
            ),
            caplog.at_level("WARNING", logger="src.gateway.review_engine"),
            respx.mock() as mock,
        ):
            mock.post(_ISSUES_COMMENTS_URL).mock(return_value=httpx.Response(201, json={"id": 1}))
            await consumer.handle(_event())

        timeout_records = [
            r for r in caplog.records if r.getMessage().startswith("review_timeout ")
        ]
        assert timeout_records, "Expected a 'review_timeout' WARNING log record"
        msg = timeout_records[0].getMessage()
        # The structured dict is %s-formatted into the message — check each key by name
        for key in (
            "event",
            "pr_number",
            "attempt",
            "stderr_excerpt",
            "codex_alive",
            "github_reachable",
            "elapsed_seconds",
        ):
            assert key in msg, f"Missing key '{key}' in review_timeout log message"


# ---------------------------------------------------------------------------
# T-239: TestRateLimiterWaitSeconds — seconds_until_next_slot
# ---------------------------------------------------------------------------


class TestRateLimiterWaitSeconds:
    def test_zero_when_slots_free(self) -> None:
        """Fresh limiter with capacity has 0 wait."""
        rl = RateLimiter(max_per_hour=5)
        assert rl.seconds_until_next_slot() == 0.0

    def test_positive_when_full(self) -> None:
        """After filling all slots, wait > 0 and <= RATE_LIMIT_WINDOW_SECONDS."""
        rl = RateLimiter(max_per_hour=1)
        rl.allow()
        wait = rl.seconds_until_next_slot()
        assert wait > 0.0
        assert wait <= RATE_LIMIT_WINDOW_SECONDS

    def test_zero_when_max_is_zero(self) -> None:
        """max_per_hour=0 means permanently blocked — no timestamp to wait on."""
        rl = RateLimiter(max_per_hour=0)
        assert rl.seconds_until_next_slot() == 0.0

    def test_drops_expired_timestamps(self) -> None:
        """Timestamps older than RATE_LIMIT_WINDOW_SECONDS are evicted."""
        rl = RateLimiter(max_per_hour=2)
        rl._timestamps = [0.0, 0.1]
        with patch(
            "src.gateway.review_engine.time.monotonic",
            return_value=RATE_LIMIT_WINDOW_SECONDS + 10,
        ):
            assert rl.seconds_until_next_slot() == 0.0


# ---------------------------------------------------------------------------
# Health probes (T-239) — exercised directly via the module functions. The
# timeout-path tests mock these out; these cover the probe code itself so
# the structured log entry's probe fields are never silent on regression.
# ---------------------------------------------------------------------------


class TestProbes:
    @pytest.mark.asyncio
    async def test_codex_probe_success_reports_version(self) -> None:
        from src.gateway.review_engine import _probe_codex_alive

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            return _FakeProcess(stdout=b"codex 1.2.3\n", returncode=0)

        with patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create):
            alive, detail = await _probe_codex_alive()
        assert alive is True
        assert "codex 1.2.3" in detail

    @pytest.mark.asyncio
    async def test_codex_probe_nonzero_exit_reports_stderr(self) -> None:
        from src.gateway.review_engine import _probe_codex_alive

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            return _FakeProcess(stderr=b"codex: command not found", returncode=127)

        with patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create):
            alive, detail = await _probe_codex_alive()
        assert alive is False
        assert "command not found" in detail

    @pytest.mark.asyncio
    async def test_codex_probe_oserror_does_not_raise(self) -> None:
        from src.gateway.review_engine import _probe_codex_alive

        async def _boom(*args: Any, **kwargs: Any) -> _FakeProcess:
            raise OSError("no such binary")

        with patch("src.gateway.review_engine._create_subprocess", side_effect=_boom):
            alive, detail = await _probe_codex_alive()
        assert alive is False
        assert "OSError" in detail

    @pytest.mark.asyncio
    async def test_github_probe_success(self) -> None:
        from src.gateway.review_engine import _probe_github_reachable

        with respx.mock() as mock:
            mock.get("https://api.github.com/zen").mock(
                return_value=httpx.Response(200, text="keep it logically awesome")
            )
            reachable, detail = await _probe_github_reachable()
        assert reachable is True
        assert "200" in detail
        assert "awesome" in detail

    @pytest.mark.asyncio
    async def test_github_probe_non200_is_reachable_false(self) -> None:
        from src.gateway.review_engine import _probe_github_reachable

        with respx.mock() as mock:
            mock.get("https://api.github.com/zen").mock(return_value=httpx.Response(503))
            reachable, detail = await _probe_github_reachable()
        assert reachable is False
        assert "503" in detail

    @pytest.mark.asyncio
    async def test_github_probe_http_error_does_not_raise(self) -> None:
        from src.gateway.review_engine import _probe_github_reachable

        with respx.mock() as mock:
            mock.get("https://api.github.com/zen").mock(side_effect=httpx.ConnectError("dns fail"))
            reachable, detail = await _probe_github_reachable()
        assert reachable is False
        assert "ConnectError" in detail


# ---------------------------------------------------------------------------
# _notify_skip — token-fetch failure must not raise
# ---------------------------------------------------------------------------


class TestNotifySkipErrorPaths:
    @pytest.fixture(autouse=True)
    def _reset_cache(self) -> Any:
        from src.gateway.review_skip_comments import reset_skip_comment_cache

        reset_skip_comment_cache()
        yield

    @pytest.mark.asyncio
    async def test_token_fetch_failure_swallowed(self, caplog: Any) -> None:
        """A token-fetch exception inside _notify_skip must not break the handler."""
        from src.gateway.review_engine import ReviewEngineConsumer

        consumer = ReviewEngineConsumer(max_per_hour=0)

        async def _boom() -> str:
            raise RuntimeError("PEM missing")

        with (
            caplog.at_level("WARNING", logger="src.gateway.review_engine"),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                side_effect=_boom,
            ),
        ):
            # Must not raise — token error is logged, short-circuit proceeds.
            await consumer.handle(_event())

        assert any("Cannot fetch Codex token" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# T-275 — settings.opencode_enabled gates stage A
# ---------------------------------------------------------------------------


class TestOpencodeEnabledFlag:
    """Stage A (opencode) must be skipped globally when ``settings.opencode_enabled``
    is False, even when the binary IS on PATH and the PEM exists. Stage B (codex)
    must still run so the PR receives a review.

    Motivation — see CLAUDE.md "Review Engine — opencode & codex invocation":
    gemma4-e4b-32k rubber-stamps :pass: regardless of prompt framing, so running
    stage A under the default model produces only noise. The flag is globally off
    by default until T-274 lands an agentic-mode reviewer that defends severity.
    """

    @staticmethod
    def _event_with_sha() -> WebhookEvent:
        return WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-275",
            repo_full_name="sachinkundu/cloglog",
            pr_number=275,
            pr_url="https://github.com/sachinkundu/cloglog/pull/275",
            head_branch="wt-disable-opencode-skip-demos",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": "f" * 40}}},
        )

    class _NoopRegistryCtx:
        async def __aenter__(self) -> object:
            from unittest.mock import AsyncMock, MagicMock

            from src.review.interfaces import PriorContext

            mock = MagicMock()
            # T-367: codex stage now reads prior_findings_and_learnings before
            # running the loop. Sequencer-level tests don't exercise memory —
            # return an empty PriorContext so the call resolves cleanly.
            mock.prior_findings_and_learnings = AsyncMock(
                return_value=PriorContext(pr_url="", turns=[])
            )
            # T-376: cap path now reads count_posted_codex_sessions from the
            # registry instead of GitHub. Default to 0 — tests that exercise
            # the cap-reaching path patch this directly.
            mock.count_posted_codex_sessions = AsyncMock(return_value=0)
            return mock

        async def __aexit__(self, *exc: object) -> bool:
            return False

    class _NoopWorktreeQueryCtx:
        """Yields a stub ``IWorktreeQuery`` whose both ``find_by_branch`` and
        ``find_by_pr_url`` return None, so ``resolve_pr_review_root`` falls
        through to the host-level root (``settings.review_source_root or
        Path.cwd()``) — the behaviour the pre-T-278 tests assumed, extended
        for the T-281 Path 0 lookup.
        """

        async def __aenter__(self) -> object:
            from unittest.mock import AsyncMock, MagicMock

            stub = MagicMock()
            stub.find_by_branch = AsyncMock(return_value=None)
            stub.find_by_pr_url = AsyncMock(return_value=None)
            return stub

        async def __aexit__(self, *exc: object) -> bool:
            return False

    @staticmethod
    def _fake_outcome() -> Any:
        return type("Outcome", (), {"turns_used": 1, "errors": []})()

    async def _run_sequencer(
        self,
        *,
        opencode_enabled: bool,
        sample_diff: str,
    ) -> tuple[list[str], list[str]]:
        """Run ``_review_pr`` with stub reviewers and return (stage_a_runs, stage_b_runs).

        Each list element is a stage label recorded by the stub ReviewLoop.
        """
        import uuid
        from unittest.mock import AsyncMock, MagicMock, patch

        stage_runs: dict[str, list[str]] = {"opencode": [], "codex": []}

        class _StubLoop:
            def __init__(self, _reviewer: object, **kwargs: object) -> None:
                self._stage = str(kwargs.get("stage", "?"))

            async def run(self, **_kwargs: object) -> object:
                stage_runs.setdefault(self._stage, []).append(self._stage)
                return TestOpencodeEnabledFlag._fake_outcome()

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=True,
            session_factory=MagicMock(),
        )
        project_id = uuid.uuid4()
        event = self._event_with_sha()

        with (
            patch(
                "src.gateway.review_engine.settings.opencode_enabled",
                opencode_enabled,
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.github_token.get_opencode_reviewer_token",
                new=AsyncMock(return_value="opencode-tok"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            # T-281: event.head_sha (f*40) won't match the host fallback's
            # real HEAD, so the resolver would attempt a temp-dir checkout.
            # Stub the creator to return None — the resolver then falls
            # through to the fallback with a drift warning, which is what
            # the pre-T-281 tests implicitly exercised.
            patch(
                "src.gateway.review_engine._create_review_checkout",
                new=AsyncMock(return_value=None),
            ),
            patch("src.gateway.review_loop.OpencodeReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.CodexReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.ReviewLoop", new=_StubLoop),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value=sample_diff)),
            patch.object(
                consumer,
                "_resolve_project_id",
                new=AsyncMock(return_value=project_id),
            ),
            patch.object(
                consumer,
                "_registry",
                new=lambda: TestOpencodeEnabledFlag._NoopRegistryCtx(),
            ),
            patch.object(
                consumer,
                "_worktree_query",
                new=lambda: TestOpencodeEnabledFlag._NoopWorktreeQueryCtx(),
            ),
        ):
            await consumer._review_pr(event)

        return stage_runs["opencode"], stage_runs["codex"]

    @pytest.mark.asyncio
    async def test_opencode_disabled_skips_stage_a(self, sample_diff: str) -> None:
        """Flag off → opencode stage never runs; codex stage still runs."""
        stage_a_runs, stage_b_runs = await self._run_sequencer(
            opencode_enabled=False,
            sample_diff=sample_diff,
        )
        assert stage_a_runs == [], (
            f"Stage A must NOT run when settings.opencode_enabled=False, "
            f"but it ran {len(stage_a_runs)} time(s)."
        )
        assert stage_b_runs == ["codex"], f"Stage B (codex) must still run; got {stage_b_runs!r}."

    @pytest.mark.asyncio
    async def test_opencode_enabled_runs_stage_a(self, sample_diff: str) -> None:
        """Flag on + binary + PEM → opencode stage runs; codex stage also runs.

        Guards against a future refactor accidentally stranding opencode in the
        disabled state.
        """
        stage_a_runs, stage_b_runs = await self._run_sequencer(
            opencode_enabled=True,
            sample_diff=sample_diff,
        )
        assert stage_a_runs == ["opencode"], (
            f"Stage A must run when settings.opencode_enabled=True; got {stage_a_runs!r}."
        )
        assert stage_b_runs == ["codex"], f"Stage B (codex) must also run; got {stage_b_runs!r}."


# ---------------------------------------------------------------------------
# T-275 round 2 — app lifespan must treat opencode-disabled as opencode-absent
# for registration/mode selection. Otherwise an opencode-only host would
# register the consumer, skip stage A (flag off) AND stage B (codex missing),
# leaving PRs with neither a review nor a skip comment.
# Codex review PR #197 MEDIUM.
# ---------------------------------------------------------------------------


class TestAppRegistrationGateT275:
    """Regression guard for the PR #197 codex-MEDIUM finding."""

    @staticmethod
    async def _run_lifespan(
        *,
        codex_ok: bool,
        opencode_ok: bool,
        opencode_enabled: bool,
    ) -> tuple[list[str], list[str]]:
        """Exercise ``lifespan()`` with the given binary/flag triple.

        Returns ``(registered_consumer_type_names, error_log_messages)``.
        """
        from fastapi import FastAPI

        from src.gateway.app import lifespan
        from src.gateway.webhook_dispatcher import webhook_dispatcher

        registrations: list[type] = []

        def _capture(consumer: object) -> None:
            registrations.append(type(consumer))

        logger_name = "src.gateway.app"
        errors: list[str] = []

        class _ErrorCapture:
            def filter(self, record: Any) -> bool:
                if record.name == logger_name and record.levelname == "ERROR":
                    errors.append(record.getMessage())
                return True

        import logging as _logging

        handler = _ErrorCapture()
        _logging.getLogger(logger_name).addFilter(handler)
        try:
            with (
                patch.object(webhook_dispatcher, "register", side_effect=_capture),
                patch(
                    "src.gateway.review_engine.is_review_agent_available",
                    return_value=codex_ok,
                ),
                patch(
                    "src.gateway.review_engine.is_opencode_available",
                    return_value=opencode_ok,
                ),
                patch(
                    "src.shared.config.settings.opencode_enabled",
                    opencode_enabled,
                ),
                # Suppress the DB-listening background task so the test does
                # not require a live Postgres NOTIFY channel.
                patch(
                    "src.gateway.notification_listener.run_notification_listener",
                    new=AsyncMock(),
                ),
            ):
                app = FastAPI()
                async with lifespan(app):
                    pass
        finally:
            _logging.getLogger(logger_name).removeFilter(handler)

        return [t.__name__ for t in registrations], errors

    @pytest.mark.asyncio
    async def test_codex_missing_plus_opencode_disabled_skips_registration(
        self,
    ) -> None:
        """Silent-regression guard: no runnable stage → consumer NOT registered."""
        registered, errors = await self._run_lifespan(
            codex_ok=False,
            opencode_ok=True,
            opencode_enabled=False,
        )
        assert "ReviewEngineConsumer" not in registered, (
            f"Consumer must NOT be registered when codex is missing AND "
            f"opencode is disabled — otherwise PRs get neither a review nor "
            f"a skip comment. registered={registered!r}"
        )
        assert any("Review pipeline disabled" in msg for msg in errors), (
            f"A loud ERROR log must explain why review is disabled; got {errors!r}"
        )

    @pytest.mark.asyncio
    async def test_codex_missing_plus_opencode_enabled_still_registers(self) -> None:
        """Flag ON + binary + no codex → opencode-only mode still works."""
        registered, _errors = await self._run_lifespan(
            codex_ok=False,
            opencode_ok=True,
            opencode_enabled=True,
        )
        assert "ReviewEngineConsumer" in registered, (
            "When opencode is enabled and the binary is present, the consumer "
            "must register for opencode-only mode even if codex is missing."
        )

    @pytest.mark.asyncio
    async def test_codex_present_plus_opencode_disabled_registers_codex_only(
        self,
    ) -> None:
        """Codex present, opencode disabled → codex-only mode (the dev default)."""
        registered, _errors = await self._run_lifespan(
            codex_ok=True,
            opencode_ok=True,
            opencode_enabled=False,
        )
        assert "ReviewEngineConsumer" in registered, (
            "Consumer must register whenever at least one effective stage is "
            "runnable; codex alone is enough."
        )


# ---------------------------------------------------------------------------
# T-278 — per-PR review root resolution
# ---------------------------------------------------------------------------


class _StubWorktreeQuery:
    """In-memory ``IWorktreeQuery`` for unit-testing ``resolve_pr_review_root``.

    ``by_branch`` / ``by_pr_url`` each hold one optional ``WorktreeRow`` and
    return it on a matching lookup. The two fields are independent because
    T-281 Path 0 (pr_url) and Path 1 (branch) can disagree — the close-out
    PR case explicitly has a pr_url hit but no branch hit. Lets the
    resolver tests run without a database; the DB path is covered
    independently in ``tests/agent/test_unit.py::TestFindWorktreeByPrUrl``
    and the DDD pin test below.
    """

    def __init__(
        self,
        row: Any | None = None,
        *,
        by_pr_url: Any | None = None,
    ) -> None:
        self._by_branch = row
        self._by_pr_url = by_pr_url

    async def find_by_branch(self, project_id: Any, branch_name: str) -> Any:
        if self._by_branch is None:
            return None
        if self._by_branch.project_id != project_id:
            return None
        if self._by_branch.branch_name != branch_name:
            return None
        return self._by_branch

    async def find_by_pr_url(self, project_id: Any, pr_url: str) -> Any:
        if not pr_url or self._by_pr_url is None:
            return None
        if self._by_pr_url.project_id != project_id:
            return None
        return self._by_pr_url


def _init_git_repo_at(path: Path) -> str:
    """Initialize a minimal git repo at ``path`` and return its HEAD SHA.

    Used by the happy-path / drift tests: ``resolve_pr_review_root`` probes
    ``git -C <path> rev-parse HEAD`` to compute the drift warning. Without
    a real repo the probe would emit ``unknown`` and the drift assertion
    would be vacuous.
    """
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    env = {
        **{k: v for k, v in __import__("os").environ.items()},
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        env=env,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


class TestResolvePrReviewRoot:
    """Per-PR review-root resolution — pr_url lookup wins over branch lookup,
    branch lookup wins over the host-level fallback, and a candidate whose
    HEAD disagrees with ``event.head_sha`` is overridden by a disposable
    temp-dir checkout at the PR's SHA. T-278 (branch + fallback) plus T-281
    (Path 0 pr_url + SHA-check temp-dir).

    CLAUDE.md "``Path.cwd()`` in backend code is a filesystem fingerprint of
    the launcher, not an invariant" has two halves: T-255 fixed the host
    level, T-278 fixed the per-PR worktree choice, and T-281 closes the
    SHA gap between them.
    """

    @staticmethod
    def _event_for_branch(
        head_branch: str,
        head_sha: str = "a" * 40,
        pr_number: int = 278,
        pr_url: str | None = None,
    ) -> WebhookEvent:
        return WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id=f"d-{pr_number}",
            repo_full_name="sachinkundu/cloglog",
            pr_number=pr_number,
            pr_url=pr_url or f"https://github.com/sachinkundu/cloglog/pull/{pr_number}",
            head_branch=head_branch,
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": head_sha}}},
        )

    @staticmethod
    def _row(project_id: Any, branch_name: str, worktree_path: str, status: str = "online") -> Any:
        from src.agent.interfaces import WorktreeRow

        return WorktreeRow(
            id=uuid.uuid4(),
            project_id=project_id,
            worktree_path=worktree_path,
            branch_name=branch_name,
            status=status,
        )

    @pytest.mark.asyncio
    async def test_happy_path_returns_worktree_path(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Matching worktree row + path exists + SHA matches → helper returns
        the worktree path with ``is_temp=False``. No drift, no fallback.
        """
        import logging as _logging

        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-foo"
        sha = _init_git_repo_at(worktree_dir)
        row = self._row(project_id, "wt-foo", str(worktree_dir))
        query = _StubWorktreeQuery(row)
        event = self._event_for_branch("wt-foo", head_sha=sha)

        with caplog.at_level(_logging.INFO, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=query
            )

        assert result.path == worktree_dir, (
            f"Expected worktree path {worktree_dir}, got {result.path}"
        )
        assert result.is_temp is False
        fallback_warnings = [
            r for r in caplog.records if "review_source=fallback" in r.getMessage()
        ]
        assert fallback_warnings == [], (
            f"Happy path must not emit fallback warning; got {fallback_warnings}"
        )
        drift_warnings = [r for r in caplog.records if "review_source_drift" in r.getMessage()]
        assert drift_warnings == [], (
            f"Matching SHAs must not emit drift warning; got {drift_warnings}"
        )

    @pytest.mark.asyncio
    async def test_fallback_no_matching_worktree(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Neither Path 0 nor Path 1 hits → fallback to
        ``settings.review_source_root``; WARNING names
        ``reason=no_matching_worktree``. SHA-check is skipped because the
        event carries an all-``f`` SHA against a fallback with no HEAD —
        we force that path by clearing head_sha instead.
        """
        import logging as _logging

        fallback_root = tmp_path / "host-fallback"
        fallback_root.mkdir()
        monkeypatch.setattr("src.gateway.review_engine.settings.review_source_root", fallback_root)
        query = _StubWorktreeQuery(None)
        event = self._event_for_branch("wt-unknown", head_sha="")

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=uuid.uuid4(), worktree_query=query
            )

        assert result.path == fallback_root, (
            f"No-match must fall back to settings.review_source_root; got {result.path}"
        )
        assert result.is_temp is False
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_source=fallback" in m and "reason=no_matching_worktree" in m for m in messages
        ), f"Missing expected WARNING; got {messages}"

    @pytest.mark.asyncio
    async def test_fallback_worktree_path_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Worktree row exists but its path is not on disk → fallback with
        ``reason=path_missing``. Cloglog agents and review share one
        filesystem (CLAUDE.md "shared-host" invariant); if the path isn't
        there, the row is stale.
        """
        import logging as _logging

        fallback_root = tmp_path / "host-fallback"
        fallback_root.mkdir()
        monkeypatch.setattr("src.gateway.review_engine.settings.review_source_root", fallback_root)
        project_id = uuid.uuid4()
        gone_path = tmp_path / "this-directory-does-not-exist"
        row = self._row(project_id, "wt-foo", str(gone_path))
        query = _StubWorktreeQuery(row)
        event = self._event_for_branch("wt-foo", head_sha="")

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=query
            )

        assert result.path == fallback_root, f"Expected fallback; got {result.path}"
        assert result.is_temp is False
        messages = [r.getMessage() for r in caplog.records]
        assert any("reason=path_missing" in m for m in messages), (
            f"Missing path_missing WARNING; got {messages}"
        )

    @pytest.mark.asyncio
    async def test_drift_falls_through_when_temp_dir_unavailable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """SHA mismatch + temp-dir creation fails → drift WARNING, stale
        worktree path still returned. "Stale worktree is better than no
        review" — the T-281 graceful-degradation path.
        """
        import logging as _logging

        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-drift"
        worktree_sha = _init_git_repo_at(worktree_dir)
        event_sha = "b" * 40 if not worktree_sha.startswith("b") else "c" * 40
        assert worktree_sha != event_sha, "Test setup error: generated SHAs accidentally matched"
        row = self._row(project_id, "wt-drift", str(worktree_dir))
        query = _StubWorktreeQuery(row)
        event = self._event_for_branch("wt-drift", head_sha=event_sha)

        # Force temp-dir creation to fail so the resolver falls through.
        monkeypatch.setattr(
            "src.gateway.review_engine._create_review_checkout",
            AsyncMock(return_value=None),
        )

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=query
            )

        assert result.path == worktree_dir, (
            f"Temp-dir failure must fall through to stale worktree; got {result.path}"
        )
        assert result.is_temp is False
        all_messages = [r.getMessage() for r in caplog.records]
        drift_messages = [m for m in all_messages if "review_source_drift" in m]
        assert drift_messages, f"Expected drift WARNING on temp-dir failure; got {all_messages}"
        assert worktree_sha[:7] in drift_messages[0]
        assert event_sha[:7] in drift_messages[0]

    @pytest.mark.asyncio
    async def test_empty_head_branch_uses_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``event.head_branch == ''`` with no pr_url hit — the helper must
        still terminate on the host-level fallback (mirrors the empty-branch
        short-circuit in ``AgentRepository``).
        """
        import logging as _logging

        fallback_root = tmp_path / "host-fallback"
        fallback_root.mkdir()
        monkeypatch.setattr("src.gateway.review_engine.settings.review_source_root", fallback_root)
        query = _StubWorktreeQuery(None)
        event = self._event_for_branch("", head_sha="")

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=uuid.uuid4(), worktree_query=query
            )

        assert result.path == fallback_root
        assert result.is_temp is False
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_source=fallback" in m and "reason=no_matching_worktree" in m for m in messages
        ), f"Empty head_branch must emit no_matching_worktree; got {messages}"

    # ----- T-281 parameterised cells (a)-(d) + pin tests -----

    @pytest.mark.asyncio
    async def test_path_0_pr_url_hit_returns_task_bound_worktree(self, tmp_path: Path) -> None:
        """Cell (a) / pin 1: a task exists with ``pr_url == event.pr_url`` and
        ``worktree_id`` pointing at a worktree → resolver returns that
        worktree's path via Path 0, without consulting the branch lookup.
        Also covers the main-agent close-out PR shape — the close-out's
        head_branch has no worktree row, so only the pr_url chain succeeds.
        """
        project_id = uuid.uuid4()
        main_clone = tmp_path / "main-clone"
        sha = _init_git_repo_at(main_clone)

        # Main agent's worktree — bound to the close-out task, NOT to the
        # close-out branch (the main agent has no worktree for that branch).
        main_row = self._row(project_id, "main", str(main_clone))

        # No row answers find_by_branch for the close-out head_branch.
        # Only find_by_pr_url returns the main-agent row.
        query = _StubWorktreeQuery(by_pr_url=main_row)
        event = self._event_for_branch(
            "wt-close-2026-04-24-foo",
            head_sha=sha,
            pr_number=281,
            pr_url="https://github.com/sachinkundu/cloglog/pull/281",
        )

        result = await resolve_pr_review_root(event, project_id=project_id, worktree_query=query)

        assert result.path == main_clone, (
            f"Main-agent close-out PR must resolve via Path 0, got {result.path}"
        )
        assert result.is_temp is False

    @pytest.mark.asyncio
    async def test_path_0_miss_then_branch_hit_returns_branch_path(self, tmp_path: Path) -> None:
        """Cell (b): no pr_url binding → fall through to branch lookup,
        return that worktree path. Typical agent PR before the close-out
        task pr_url is wired up.
        """
        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-agent"
        sha = _init_git_repo_at(worktree_dir)
        row = self._row(project_id, "wt-agent", str(worktree_dir))
        # Path 0 explicitly miss; Path 1 hits.
        query = _StubWorktreeQuery(by_pr_url=None, row=row)
        event = self._event_for_branch("wt-agent", head_sha=sha, pr_number=282)

        result = await resolve_pr_review_root(event, project_id=project_id, worktree_query=query)

        assert result.path == worktree_dir
        assert result.is_temp is False

    @pytest.mark.asyncio
    async def test_path_0_and_branch_miss_falls_to_host_fallback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cell (c): both paths miss → host-level fallback, no temp dir
        (head_sha empty to skip SHA check). No warnings about
        ``review_source_drift``.
        """
        fallback_root = tmp_path / "host-fallback"
        fallback_root.mkdir()
        monkeypatch.setattr("src.gateway.review_engine.settings.review_source_root", fallback_root)
        query = _StubWorktreeQuery(None)
        event = self._event_for_branch("wt-nothing", head_sha="", pr_number=283)

        result = await resolve_pr_review_root(event, project_id=uuid.uuid4(), worktree_query=query)

        assert result.path == fallback_root
        assert result.is_temp is False

    @pytest.mark.asyncio
    async def test_sha_mismatch_triggers_temp_dir_checkout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cell (d) / pin 2: Path 0 or Path 1 yields a candidate whose HEAD
        differs from ``event.head_sha`` → resolver calls
        ``_create_review_checkout`` and returns the temp path with
        ``is_temp=True``. Captures the webhook-race + close-out scenarios
        the T-281 docstring calls out.
        """
        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-stale"
        worktree_sha = _init_git_repo_at(worktree_dir)
        event_sha = "b" * 40 if not worktree_sha.startswith("b") else "c" * 40
        assert worktree_sha != event_sha
        row = self._row(project_id, "wt-stale", str(worktree_dir))
        query = _StubWorktreeQuery(row)
        event = self._event_for_branch("wt-stale", head_sha=event_sha, pr_number=284)

        fake_temp = tmp_path / "temp-checkout"
        fake_temp.mkdir()
        create_mock = AsyncMock(return_value=fake_temp)
        monkeypatch.setattr("src.gateway.review_engine._create_review_checkout", create_mock)

        result = await resolve_pr_review_root(event, project_id=project_id, worktree_query=query)

        assert result.path == fake_temp, (
            f"SHA mismatch must route to temp checkout, got {result.path}"
        )
        assert result.is_temp is True
        create_mock.assert_awaited_once()
        # Verify the helper was called with the PR's head_sha, not the worktree's.
        args, kwargs = create_mock.call_args
        call_sha = kwargs.get("head_sha") or (args[1] if len(args) > 1 else None)
        assert call_sha == event_sha, (
            f"Temp checkout must be materialized at event.head_sha; got {call_sha!r}"
        )

    @pytest.mark.asyncio
    async def test_pr_url_binding_preferred_over_branch_when_both_hit(self, tmp_path: Path) -> None:
        """If both Path 0 and Path 1 would return a viable candidate,
        Path 0 wins. Typically they point at the same worktree; this test
        pins the *order* by making them point at different paths and
        asserting Path 0's wins.
        """
        project_id = uuid.uuid4()
        by_pr_url_dir = tmp_path / "wt-canonical"
        sha = _init_git_repo_at(by_pr_url_dir)
        by_branch_dir = tmp_path / "wt-branch-only"
        _init_git_repo_at(by_branch_dir)

        pr_url_row = self._row(project_id, "wt-canonical", str(by_pr_url_dir))
        branch_row = self._row(project_id, "wt-branch-only", str(by_branch_dir))
        query = _StubWorktreeQuery(by_pr_url=pr_url_row, row=branch_row)
        event = self._event_for_branch("wt-branch-only", head_sha=sha, pr_number=285)

        result = await resolve_pr_review_root(event, project_id=project_id, worktree_query=query)

        assert result.path == by_pr_url_dir, (
            "Path 0 (pr_url) must win over Path 1 (branch) when both match"
        )


class TestResolvePrReviewRootRepoRouting:
    """T-350 — resolver must consult ``event.repo_full_name`` before
    falling back to the host-level ``review_source_root``. The original
    incident: antisocial PR #2 was reviewed against cloglog's source
    because the resolver was repo-blind and the PR's branch had no
    registered worktree on the host. The fix introduces
    ``settings.review_repo_roots`` — a per-repo registry consulted
    before the legacy fallback. When the registry is non-empty and an
    incoming PR's repo is absent from it AND no worktree on this host
    owns its branch, the resolver REFUSES (returns ``None``) instead
    of routing the review to the wrong repo's source.
    """

    @staticmethod
    def _event(
        repo_full_name: str,
        head_branch: str,
        *,
        head_sha: str = "",
        pr_number: int = 350,
    ) -> WebhookEvent:
        return WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id=f"d-{repo_full_name}-{pr_number}",
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            pr_url=f"https://github.com/{repo_full_name}/pull/{pr_number}",
            head_branch=head_branch,
            base_branch="main",
            sender="sachinkundu",
            raw={
                "pull_request": {"head": {"sha": head_sha}},
                "repository": {"full_name": repo_full_name},
            },
        )

    @staticmethod
    def _row(project_id: Any, branch_name: str, worktree_path: str) -> Any:
        from src.agent.interfaces import WorktreeRow

        return WorktreeRow(
            id=uuid.uuid4(),
            project_id=project_id,
            worktree_path=worktree_path,
            branch_name=branch_name,
            status="online",
        )

    @pytest.mark.asyncio
    async def test_resolve_pr_review_root_skips_unrelated_repo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """T-350 acceptance #1: webhook for ``sachinkundu/antisocial`` with
        no matching worktree on this host AND no registry entry for that
        repo → resolver returns ``None``. Pins the refusal: the original
        antisocial PR #2 incident took this exact shape (close-wave branch
        ``wt-close-2026-04-29-wave-1`` had no worktree row, the registry
        wasn't consulted, fallback handed cloglog-prod to codex).
        """
        import logging as _logging

        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        # Registry exists and has cloglog — but NOT antisocial. The
        # incoming PR's repo must be refused, not silently routed
        # elsewhere.
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {"sachinkundu/cloglog": cloglog_root},
        )
        # Also pin the legacy fallback to a real path so a regression
        # that ignores the registry would visibly route there — making
        # the test fail with a path comparison rather than vacuously
        # passing.
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            cloglog_root,
        )
        query = _StubWorktreeQuery(None)
        event = self._event(
            "sachinkundu/antisocial",
            "wt-close-2026-04-29-wave-1",
        )

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=uuid.uuid4(), worktree_query=query
            )

        assert result is None, (
            "Unconfigured repo with no worktree match must REFUSE — got "
            f"{result}. Returning a candidate here re-opens the T-350 "
            "cross-repo leak (antisocial PR reviewed against cloglog source)."
        )
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_source=refused" in m and "reason=unconfigured_repo" in m for m in messages
        ), (
            "Refusal must log review_source=refused reason=unconfigured_repo for "
            f"operator visibility; got {messages}"
        )

    @pytest.mark.asyncio
    async def test_close_wave_pr_on_cloglog_still_routes_to_cloglog(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """T-350 acceptance #2: a cloglog close-wave PR (no worktree row
        for the close-off branch, no pr_url binding) MUST still resolve
        to cloglog's review root via the registry. Without this the fix
        would regress every cloglog close-wave / hand-created PR.
        """
        cloglog_root = tmp_path / "cloglog-prod"
        sha = _init_git_repo_at(cloglog_root)
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {"sachinkundu/cloglog": cloglog_root},
        )
        query = _StubWorktreeQuery(None)
        event = self._event(
            "sachinkundu/cloglog",
            "wt-close-2026-04-29-wave-7",
            head_sha=sha,
        )

        result = await resolve_pr_review_root(event, project_id=uuid.uuid4(), worktree_query=query)

        assert result is not None, (
            "Cloglog close-wave PR must route to cloglog's review root via "
            "registry — got None. The fix would otherwise break every "
            "close-wave / hand-created cloglog PR."
        )
        assert result.path == cloglog_root, (
            f"Expected registry path {cloglog_root}; got {result.path}"
        )
        assert result.is_temp is False

    @pytest.mark.asyncio
    async def test_existing_worktree_branch_lookup_unchanged_cloglog(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """T-350 acceptance #3 (cloglog half): a registered cloglog
        worktree for the PR's branch hits Path 1 regardless of the
        registry — the registry is the no-worktree-match safety net,
        not a replacement for the worktree lookup. Pins that adding the
        registry never displaces a live worktree row.
        """
        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-cloglog-feature"
        sha = _init_git_repo_at(worktree_dir)
        # Registry deliberately points elsewhere — Path 1 must win.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {"sachinkundu/cloglog": elsewhere},
        )
        row = self._row(project_id, "wt-cloglog-feature", str(worktree_dir))
        query = _StubWorktreeQuery(row)
        event = self._event(
            "sachinkundu/cloglog",
            "wt-cloglog-feature",
            head_sha=sha,
        )

        result = await resolve_pr_review_root(event, project_id=project_id, worktree_query=query)

        assert result is not None and result.path == worktree_dir, (
            f"Path 1 (worktree branch) must beat the registry; got {result}"
        )

    @pytest.mark.asyncio
    async def test_existing_worktree_branch_lookup_unchanged_foreign_repo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """T-350 acceptance #3 (foreign-repo half): same regression pin,
        but for a non-cloglog repo with a registered worktree row. This
        is the antisocial PR #3 control case: PR #3 was reviewed
        correctly because Path 1 hit on its registered worktree, even
        though the host's review_source_root pointed at cloglog.
        """
        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "antisocial-wt-bootstrap"
        sha = _init_git_repo_at(worktree_dir)
        # Registry is empty for antisocial, but Path 1 still wins.
        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {"sachinkundu/cloglog": cloglog_root},
        )
        row = self._row(project_id, "wt-f0-bootstrap", str(worktree_dir))
        query = _StubWorktreeQuery(row)
        event = self._event(
            "sachinkundu/antisocial",
            "wt-f0-bootstrap",
            head_sha=sha,
            pr_number=3,
        )

        result = await resolve_pr_review_root(event, project_id=project_id, worktree_query=query)

        assert result is not None and result.path == worktree_dir, (
            "Antisocial PR #3 control case: Path 1 must still win for a "
            f"registered foreign-repo worktree; got {result}"
        )

    @pytest.mark.asyncio
    async def test_review_repo_roots_registry_lookup(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """T-350 acceptance #4: a webhook with ``repo_full_name`` in
        the registry AND no worktree match → resolver returns the
        registry path. This is option (a) — per-repo routing for
        repos whose checkouts live on this host but whose PRs aren't
        owned by a worktree (e.g. external contributors, hand-created
        PRs).
        """
        import logging as _logging

        antisocial_root = tmp_path / "antisocial"
        sha = _init_git_repo_at(antisocial_root)
        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {
                "sachinkundu/cloglog": cloglog_root,
                "sachinkundu/antisocial": antisocial_root,
            },
        )
        query = _StubWorktreeQuery(None)
        event = self._event(
            "sachinkundu/antisocial",
            "feature/external",
            head_sha=sha,
            pr_number=42,
        )

        with caplog.at_level(_logging.INFO, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=uuid.uuid4(), worktree_query=query
            )

        assert result is not None, "Registry hit must produce a candidate; got None"
        assert result.path == antisocial_root, (
            f"Registry must route antisocial PR to antisocial root; got {result.path}"
        )
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_source=registry" in m and "sachinkundu/antisocial" in m for m in messages
        ), f"Registry hit must log review_source=registry; got {messages}"

    @pytest.mark.asyncio
    async def test_temp_checkout_anchored_at_registry_path_not_review_source_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """T-350 codex round 2: when Path 2 (registry) wins AND the
        candidate's HEAD disagrees with ``event.head_sha``, the temp-dir
        checkout must be materialised under the registry-resolved main
        clone — NOT under ``settings.review_source_root``.

        Anchoring at ``review_source_root`` (typically cloglog-prod) for
        a foreign-repo PR runs ``git worktree add ... <foreign sha>``
        against cloglog-prod's object DB and ``git fetch origin
        <foreign branch>`` against cloglog's origin: neither resolves
        the foreign objects, so the temp-checkout silently degrades to
        a stale review. Pin: the resolver must pass the registry path
        as ``main_clone`` to ``_create_review_checkout`` and to the
        returned ``PrReviewRoot`` (so finally-block cleanup runs
        against the right ``git worktree`` list).
        """
        antisocial_root = tmp_path / "antisocial"
        antisocial_sha = _init_git_repo_at(antisocial_root)
        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        # Registry hit for antisocial; legacy fallback (cloglog-prod) is
        # the WRONG anchor — pin asserts the resolver does not use it.
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {
                "sachinkundu/cloglog": cloglog_root,
                "sachinkundu/antisocial": antisocial_root,
            },
        )
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            cloglog_root,
        )

        # Force a SHA mismatch so the temp-checkout branch executes.
        event_sha = "b" * 40 if not antisocial_sha.startswith("b") else "c" * 40
        assert event_sha != antisocial_sha

        fake_temp = tmp_path / "temp-checkout"
        fake_temp.mkdir()
        create_mock = AsyncMock(return_value=fake_temp)
        monkeypatch.setattr("src.gateway.review_engine._create_review_checkout", create_mock)

        query = _StubWorktreeQuery(None)
        event = self._event(
            "sachinkundu/antisocial",
            "feature/external",
            head_sha=event_sha,
            pr_number=99,
        )

        result = await resolve_pr_review_root(event, project_id=uuid.uuid4(), worktree_query=query)

        assert result is not None and result.is_temp is True, (
            f"Expected is_temp=True PrReviewRoot; got {result}"
        )
        # The temp-checkout helper must receive the registry path as its
        # main_clone — NOT cloglog-prod (settings.review_source_root).
        create_mock.assert_awaited_once()
        args, kwargs = create_mock.call_args
        call_anchor = args[0] if args else kwargs.get("main_clone")
        assert call_anchor == antisocial_root, (
            "T-350 codex round 2: _create_review_checkout must be anchored "
            "at the registry path for the PR's repo, not at "
            f"settings.review_source_root. Got anchor={call_anchor!r}; "
            f"expected {antisocial_root!r}."
        )
        # The PrReviewRoot returned to the caller must carry the same
        # anchor as main_clone, so finally-block cleanup runs against
        # the registry path's worktree list, not cloglog-prod's.
        assert result.main_clone == antisocial_root, (
            "PrReviewRoot.main_clone must point at the registry root for "
            f"finally-block cleanup; got {result.main_clone!r}."
        )

    @pytest.mark.asyncio
    async def test_temp_checkout_anchor_for_path1_foreign_repo_uses_worktree_common_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """T-350 codex round 3: a Path 1 (worktree branch) hit for a
        foreign repo NOT in the registry must still anchor the temp-
        checkout at the foreign repo's main clone — derived from the
        worktree's ``--git-common-dir`` — rather than falling back to
        ``settings.review_source_root``.

        Failure mode codex caught: registry lists only cloglog;
        antisocial has a registered worktree, so Path 1 returns it;
        SHA mismatch then materialises a temp-checkout under
        cloglog-prod, which can't resolve antisocial's objects.
        """
        import os as _os
        import subprocess as _subprocess

        # Simulate the antisocial main clone + a linked worktree off it.
        # ``_init_git_repo_at`` creates a real git repo; the worktree's
        # ``rev-parse --git-common-dir`` points back at the main clone.
        antisocial_main = tmp_path / "antisocial-main"
        _init_git_repo_at(antisocial_main)
        antisocial_worktree = tmp_path / "antisocial-wt-foo"
        env = {
            **{k: v for k, v in _os.environ.items()},
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        _subprocess.run(
            [
                "git",
                "-C",
                str(antisocial_main),
                "worktree",
                "add",
                "-b",
                "wt-foo",
                str(antisocial_worktree),
            ],
            check=True,
            capture_output=True,
            env=env,
        )
        worktree_sha = _subprocess.run(
            ["git", "-C", str(antisocial_worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()

        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        # Registry has cloglog ONLY — antisocial relies on worktree
        # common-dir derivation. settings.review_source_root also
        # points at cloglog so a regression that fell through there
        # would visibly route the wrong way and fail the assert.
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {"sachinkundu/cloglog": cloglog_root},
        )
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            cloglog_root,
        )

        # Path 1 hit on the antisocial worktree row.
        project_id = uuid.uuid4()
        row = self._row(project_id, "wt-foo", str(antisocial_worktree))
        query = _StubWorktreeQuery(row)

        # Force a SHA mismatch so the temp-checkout branch executes.
        event_sha = "b" * 40 if not worktree_sha.startswith("b") else "c" * 40
        assert event_sha != worktree_sha
        event = self._event(
            "sachinkundu/antisocial",
            "wt-foo",
            head_sha=event_sha,
            pr_number=7,
        )

        fake_temp = tmp_path / "temp-checkout"
        fake_temp.mkdir()
        create_mock = AsyncMock(return_value=fake_temp)
        monkeypatch.setattr("src.gateway.review_engine._create_review_checkout", create_mock)

        result = await resolve_pr_review_root(event, project_id=project_id, worktree_query=query)

        assert result is not None and result.is_temp is True
        create_mock.assert_awaited_once()
        args, kwargs = create_mock.call_args
        call_anchor = args[0] if args else kwargs.get("main_clone")
        # Resolve symlinks (macOS /private/var ↔ /var; tmp_path can carry one).
        assert Path(call_anchor).resolve() == antisocial_main.resolve(), (
            "T-350 codex round 3: Path 1 foreign-repo worktree hit must "
            "anchor the temp-checkout at the worktree's --git-common-dir "
            f"parent (antisocial main clone), not review_source_root. "
            f"Got anchor={call_anchor!r}; expected {antisocial_main!r}."
        )
        assert Path(result.main_clone).resolve() == antisocial_main.resolve(), (
            "PrReviewRoot.main_clone must match the temp-checkout anchor "
            f"for cleanup symmetry; got {result.main_clone!r}."
        )

    @pytest.mark.asyncio
    async def test_stale_registry_entry_falls_through_to_worktree_common_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """T-350 codex round 4: a stale/mistyped registry entry must not
        override a valid Path 1 worktree hit. The original round-3 fix
        used the registry path unconditionally — if it pointed at a
        missing or non-git directory, ``_create_review_checkout`` would
        fail and the review would silently fall back to the stale
        candidate.

        Pin: registry has the correct repo key but a path that doesn't
        exist; Path 1 returns a real linked worktree; SHA mismatch
        triggers the temp-checkout. Anchor must come from the worktree's
        ``--git-common-dir``, not the bad registry entry. The resolver
        also logs a WARNING naming the bad path so an operator can fix
        the config.
        """
        import logging as _logging
        import os as _os
        import subprocess as _subprocess

        # Real antisocial main + linked worktree, same shape as the
        # round-3 test.
        antisocial_main = tmp_path / "antisocial-main"
        _init_git_repo_at(antisocial_main)
        antisocial_worktree = tmp_path / "antisocial-wt-bar"
        env = {
            **{k: v for k, v in _os.environ.items()},
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        _subprocess.run(
            [
                "git",
                "-C",
                str(antisocial_main),
                "worktree",
                "add",
                "-b",
                "wt-bar",
                str(antisocial_worktree),
            ],
            check=True,
            capture_output=True,
            env=env,
        )
        worktree_sha = _subprocess.run(
            ["git", "-C", str(antisocial_worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout.strip()

        # Bad registry: antisocial points at a path that doesn't exist.
        bad_registry_path = tmp_path / "missing-does-not-exist"
        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {
                "sachinkundu/cloglog": cloglog_root,
                "sachinkundu/antisocial": bad_registry_path,
            },
        )
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            cloglog_root,
        )

        # Path 1 hit on the antisocial worktree row.
        project_id = uuid.uuid4()
        row = self._row(project_id, "wt-bar", str(antisocial_worktree))
        query = _StubWorktreeQuery(row)

        # Force a SHA mismatch so the temp-checkout branch executes.
        event_sha = "b" * 40 if not worktree_sha.startswith("b") else "c" * 40
        assert event_sha != worktree_sha
        event = self._event(
            "sachinkundu/antisocial",
            "wt-bar",
            head_sha=event_sha,
            pr_number=8,
        )

        fake_temp = tmp_path / "temp-checkout-stale"
        fake_temp.mkdir()
        create_mock = AsyncMock(return_value=fake_temp)
        monkeypatch.setattr("src.gateway.review_engine._create_review_checkout", create_mock)

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=query
            )

        assert result is not None and result.is_temp is True
        create_mock.assert_awaited_once()
        args, kwargs = create_mock.call_args
        call_anchor = args[0] if args else kwargs.get("main_clone")
        # Anchor must be the worktree's common-dir parent — NOT the
        # bad registry path.
        assert Path(call_anchor).resolve() == antisocial_main.resolve(), (
            "T-350 codex round 4: a non-git registry entry must not "
            "override the valid Path 1 worktree's common-dir derivation. "
            f"Got anchor={call_anchor!r}; expected {antisocial_main!r}; "
            f"bad registry entry was {bad_registry_path!r}."
        )
        assert Path(call_anchor).resolve() != bad_registry_path.resolve(), (
            "Bad registry entry leaked into the temp-checkout call"
        )
        # Operator visibility: WARNING names the bad config path.
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_repo_roots" in m
            and "sachinkundu/antisocial" in m
            and "not a usable git repo" in m
            for m in messages
        ), (
            "Bad registry entry must produce a WARNING naming the repo "
            f"and the path so the operator can fix it; got {messages}"
        )

    @pytest.mark.asyncio
    async def test_path2_registry_refuses_existing_non_git_directory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """T-350 codex round 5 HIGH: Path 2 must validate the registry
        entry via ``--git-common-dir``, not just ``is_dir()``. A typo'd
        registry value pointing at an existing non-git directory was
        being accepted as a successful registry hit; codex/opencode
        would then review the wrong tree (or empty dir) instead of
        refusing.

        Pin: registry has the antisocial key but points it at a plain
        directory that is not a git repo. The resolver must NOT
        return that directory as a candidate; it must fall through to
        the existing refusal path (registry non-empty + repo absent
        from a usable registry → return None).
        """
        import logging as _logging

        not_a_repo = tmp_path / "antisocial-typo"
        not_a_repo.mkdir()  # exists, but is not git-init'd
        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {
                "sachinkundu/cloglog": cloglog_root,
                "sachinkundu/antisocial": not_a_repo,
            },
        )
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            cloglog_root,
        )
        query = _StubWorktreeQuery(None)
        event = self._event(
            "sachinkundu/antisocial",
            "feature/typo",
            head_sha="",
            pr_number=11,
        )

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=uuid.uuid4(), worktree_query=query
            )

        assert result is None, (
            "Path 2 must refuse a registry entry that is not a git repo, "
            f"not return it as a candidate; got {result}"
        )
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_source=fallback" in m
            and "registry_path_invalid" in m
            and "sachinkundu/antisocial" in m
            for m in messages
        ), f"Missing registry_path_invalid WARNING; got {messages}"
        assert any(
            "review_source=refused" in m and "reason=unconfigured_repo" in m for m in messages
        ), f"Refusal path must still fire; got {messages}"

    @pytest.mark.asyncio
    async def test_degraded_path_refuses_unconfigured_repo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """T-350 codex round 5 MEDIUM: the single-turn degraded review
        path (``session_factory=None`` or missing ``head_sha``) must
        also honour the ``review_repo_roots`` refusal contract. Before
        this fix the degraded branch hard-coded
        ``settings.review_source_root or Path.cwd()`` and reviewed
        unconfigured foreign PRs against cloglog's source — recreating
        the antisocial PR #2 leak whenever a deployment used the
        no-factory constructor or an event arrived without head_sha.

        Pin: feed a foreign-repo PR through ``ReviewEngineConsumer()``
        (no ``session_factory`` → degraded path), with a registry that
        DOES NOT include that repo. Assert codex is never spawned, a
        ``UNCONFIGURED_REPO`` skip comment is posted, and the
        degraded-path WARNING fires.
        """
        cloglog_root = tmp_path / "cloglog-prod"
        cloglog_root.mkdir()
        # Registry has cloglog only — antisocial event must be refused.
        # Set review_source_root to the legacy fallback so a regression
        # that bypassed the new refusal would visibly route there
        # (codex argv would carry `-C cloglog-prod`).
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_repo_roots",
            {"sachinkundu/cloglog": cloglog_root},
        )
        monkeypatch.setattr(
            "src.gateway.review_engine.settings.review_source_root",
            cloglog_root,
        )

        consumer = ReviewEngineConsumer(max_per_hour=10)
        captured_argv: list[Any] = []

        def _record_spawn(*args: Any, **kwargs: Any) -> None:
            captured_argv.append(args)
            raise AssertionError(
                "codex MUST NOT be spawned for an unconfigured-repo PR on "
                "the degraded path; registry refusal must short-circuit"
            )

        # Antisocial PR through the degraded path.
        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-T350-degraded",
            repo_full_name="sachinkundu/antisocial",
            pr_number=99,
            pr_url="https://github.com/sachinkundu/antisocial/pull/99",
            head_branch="wt-close-2026-04-29-wave-1",
            base_branch="main",
            sender="sachinkundu",
            raw={},
        )

        post_skip_calls: list[Any] = []

        async def _capture_skip(repo: str, pr: int, reason: Any, body: str, token: str) -> None:
            post_skip_calls.append((repo, pr, reason, body))

        with (
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.gateway.review_engine.latest_codex_review_is_approval",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "src.gateway.review_engine._spawn",
                side_effect=_record_spawn,
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
                "src.gateway.review_engine.ReviewEngineConsumer._fetch_pr_diff",
                new=AsyncMock(
                    return_value=(
                        "diff --git a/foo.py b/foo.py\n"
                        "index 1..2 100644\n--- a/foo.py\n+++ b/foo.py\n"
                        "@@ -1 +1 @@\n-old\n+new\n"
                    )
                ),
            ),
            patch(
                "src.gateway.review_engine.post_skip_comment",
                new=AsyncMock(side_effect=_capture_skip),
            ),
        ):
            await consumer.handle(event)

        assert captured_argv == [], (
            "Degraded path MUST refuse before spawning codex; "
            f"unexpected spawn args={captured_argv}"
        )
        assert len(post_skip_calls) == 1, (
            f"Expected exactly one skip comment; got {post_skip_calls}"
        )
        repo, pr_num, reason, _body = post_skip_calls[0]
        from src.gateway.review_skip_comments import SkipReason

        assert repo == "sachinkundu/antisocial"
        assert pr_num == 99
        assert reason == SkipReason.UNCONFIGURED_REPO, (
            f"Expected UNCONFIGURED_REPO skip; got {reason}"
        )


class TestReviewEngineDDDBoundary:
    """T-278 DDD backstop — Gateway's review engine must NOT import the
    Agent context's models or repository (priority-3 DDD violation per
    ``docs/ddd-context-map.md``; caught as CRITICAL on PR #187 round 2
    for the Review context — this pin applies the same rule to the
    Agent → Gateway seam.

    Asserts absence (not presence) so leak-after-fix regressions fail
    automatically — see CLAUDE.md "Leak-after-fix" rule.
    """

    _REVIEW_ENGINE_PATH = Path("src/gateway/review_engine.py")

    def test_gateway_review_engine_does_not_import_agent_models(self) -> None:
        text = self._REVIEW_ENGINE_PATH.read_text()
        assert "from src.agent.models" not in text, (
            f"{self._REVIEW_ENGINE_PATH} imports from src.agent.models — "
            "priority-3 DDD violation. Gateway must consume Agent only via "
            "interfaces/services factories. T-278."
        )
        assert "import src.agent.models" not in text, (
            f"{self._REVIEW_ENGINE_PATH} imports src.agent.models — "
            "priority-3 DDD violation. T-278."
        )

    def test_gateway_review_engine_does_not_import_agent_repository(self) -> None:
        text = self._REVIEW_ENGINE_PATH.read_text()
        assert "from src.agent.repository" not in text, (
            f"{self._REVIEW_ENGINE_PATH} imports from src.agent.repository — "
            "priority-3 DDD violation. Gateway must consume Agent only via "
            "interfaces/services factories. T-278."
        )
        assert "import src.agent.repository" not in text, (
            f"{self._REVIEW_ENGINE_PATH} imports src.agent.repository — "
            "priority-3 DDD violation. T-278."
        )

    def test_gateway_review_engine_imports_agent_only_via_ohs(self) -> None:
        """Allow-list the exact Agent-context imports Gateway is permitted
        to have. Any new Gateway → Agent edge must either add its name to
        this allow-list or route through the Protocol/factory boundary.
        """
        import ast

        tree = ast.parse(self._REVIEW_ENGINE_PATH.read_text())
        agent_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module.startswith("src.agent"):
                    for alias in node.names:
                        agent_imports.append(f"{node.module}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("src.agent"):
                        agent_imports.append(alias.name)

        allowed = {
            "src.agent.interfaces.IWorktreeQuery",
            "src.agent.services.make_worktree_query",
        }
        disallowed = [name for name in agent_imports if name not in allowed]
        assert not disallowed, (
            "Gateway review engine imported non-OHS Agent names: "
            f"{disallowed}. Only IWorktreeQuery + make_worktree_query are "
            "allowed. T-278."
        )


class TestReviewPrUsesWorktreeProjectRoot:
    """Integration pin — ``_review_pr`` routes the worktree path into the
    reviewer constructors. A regression that bypassed the resolver (e.g.
    a partial merge reverting the call-site to ``settings.review_source_root
    or Path.cwd()``) would silently re-open the T-278 bug; this test makes
    that drift fail the suite.
    """

    class _RecordingRegistryCtx:
        async def __aenter__(self) -> object:
            from unittest.mock import AsyncMock, MagicMock

            from src.review.interfaces import PriorContext

            mock = MagicMock()
            # T-367: codex stage now reads prior_findings_and_learnings before
            # running the loop. These T-278 tests don't exercise memory —
            # return an empty PriorContext so the call resolves cleanly.
            mock.prior_findings_and_learnings = AsyncMock(
                return_value=PriorContext(pr_url="", turns=[])
            )
            # T-376: cap path now reads count_posted_codex_sessions from the
            # registry instead of GitHub. Default to 0 — tests that exercise
            # the cap-reaching path patch this directly.
            mock.count_posted_codex_sessions = AsyncMock(return_value=0)
            return mock

        async def __aexit__(self, *exc: object) -> bool:
            return False

    @pytest.mark.asyncio
    async def test_review_pr_passes_worktree_path_to_reviewer(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-t278"
        worktree_sha = _init_git_repo_at(worktree_dir)

        from src.agent.interfaces import WorktreeRow

        row = WorktreeRow(
            id=uuid.uuid4(),
            project_id=project_id,
            worktree_path=str(worktree_dir),
            branch_name="wt-t278",
            status="online",
        )

        class _MatchingQueryCtx:
            async def __aenter__(self) -> object:
                stub = MagicMock()
                stub.find_by_branch = AsyncMock(return_value=row)
                stub.find_by_pr_url = AsyncMock(return_value=None)
                return stub

            async def __aexit__(self, *exc: object) -> bool:
                return False

        reviewer_init_args: list[Path] = []

        class _StubLoop:
            def __init__(self, reviewer: object, **kwargs: object) -> None:
                # ``reviewer`` is the mocked OpencodeReviewer/CodexReviewer
                # instance. We inspect the MagicMock call_args on the class
                # patch instead — see ``captured_roots`` below.
                self._stage = str(kwargs.get("stage", "?"))

            async def run(self, **_kwargs: object) -> object:
                return type("Outcome", (), {"turns_used": 1, "errors": []})()

        # SHA matches the worktree HEAD so the resolver returns the worktree
        # directly, not a temp checkout. Mismatch would be the T-281 temp-dir
        # path which is covered by ``test_review_pr_cleans_up_temp_checkout``.
        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-t278",
            repo_full_name="sachinkundu/cloglog",
            pr_number=278,
            pr_url="https://github.com/sachinkundu/cloglog/pull/278",
            head_branch="wt-t278",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": worktree_sha}}},
        )

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=MagicMock(),
        )

        with (
            patch(
                "src.gateway.review_engine.settings.opencode_enabled",
                False,
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            patch("src.gateway.review_loop.CodexReviewer") as codex_cls,
            patch("src.gateway.review_loop.ReviewLoop", new=_StubLoop),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value="diff")),
            patch.object(
                consumer,
                "_resolve_project_id",
                new=AsyncMock(return_value=project_id),
            ),
            patch.object(
                consumer,
                "_registry",
                new=lambda: TestReviewPrUsesWorktreeProjectRoot._RecordingRegistryCtx(),
            ),
            patch.object(consumer, "_worktree_query", new=lambda: _MatchingQueryCtx()),
        ):
            await consumer._review_pr(event)
            reviewer_init_args.extend(
                call.args[0] for call in codex_cls.call_args_list if call.args
            )

        assert reviewer_init_args, "Codex reviewer was never constructed — check the test wiring."
        assert reviewer_init_args[0] == worktree_dir, (
            f"Expected CodexReviewer project_root={worktree_dir}, got "
            f"{reviewer_init_args[0]!r}. Regression: _review_pr bypassed "
            "resolve_pr_review_root. T-278."
        )

    @pytest.mark.asyncio
    async def test_review_pr_cleans_up_temp_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin 3 / cell (e): when the resolver returns a temp-dir checkout
        (``is_temp=True``), ``_review_pr`` MUST remove it after review,
        even if the review stage raises. The cleanup runs from a ``finally``
        block in the caller — otherwise a flaky reviewer leaks the checkout
        and ``.cloglog/review-checkouts/`` grows unbounded on prod.
        """
        from unittest.mock import AsyncMock, MagicMock

        project_id = uuid.uuid4()
        fake_temp = tmp_path / "temp-checkout-285"
        fake_temp.mkdir()
        main_clone = tmp_path / "main-clone"
        _init_git_repo_at(main_clone)

        from src.gateway.review_engine import PrReviewRoot

        class _TempRootQueryCtx:
            async def __aenter__(self) -> object:
                # The resolver call is patched below; this stub just exists
                # so ``_worktree_query`` returns something that implements
                # the Protocol surface.
                stub = MagicMock()
                stub.find_by_branch = AsyncMock(return_value=None)
                stub.find_by_pr_url = AsyncMock(return_value=None)
                return stub

            async def __aexit__(self, *exc: object) -> bool:
                return False

        class _StubLoop:
            def __init__(self, reviewer: object, **kwargs: object) -> None:
                self._stage = str(kwargs.get("stage", "?"))

            async def run(self, **_kwargs: object) -> object:
                return type("Outcome", (), {"turns_used": 1, "errors": []})()

        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-t281-e",
            repo_full_name="sachinkundu/cloglog",
            pr_number=285,
            pr_url="https://github.com/sachinkundu/cloglog/pull/285",
            head_branch="wt-t281-temp",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": "d" * 40}}},
        )

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=MagicMock(),
        )

        # Force the resolver to return a temp-rooted PrReviewRoot so the
        # cleanup branch fires. ``_remove_review_checkout`` is then asserted
        # to have been awaited.
        temp_root = PrReviewRoot(path=fake_temp, is_temp=True, main_clone=main_clone)
        remove_mock = AsyncMock()
        monkeypatch.setattr("src.gateway.review_engine._remove_review_checkout", remove_mock)
        monkeypatch.setattr(
            "src.gateway.review_engine.resolve_pr_review_root",
            AsyncMock(return_value=temp_root),
        )

        with (
            patch(
                "src.gateway.review_engine.settings.opencode_enabled",
                False,
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            patch("src.gateway.review_loop.CodexReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.ReviewLoop", new=_StubLoop),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value="diff")),
            patch.object(
                consumer,
                "_resolve_project_id",
                new=AsyncMock(return_value=project_id),
            ),
            patch.object(
                consumer,
                "_registry",
                new=lambda: TestReviewPrUsesWorktreeProjectRoot._RecordingRegistryCtx(),
            ),
            patch.object(consumer, "_worktree_query", new=lambda: _TempRootQueryCtx()),
        ):
            await consumer._review_pr(event)

        remove_mock.assert_awaited_once()
        args, _ = remove_mock.call_args
        # Cleanup must be called with (main_clone, temp_path) so `git
        # worktree remove --force` runs from the repo that owns the
        # disposable worktree.
        assert args[0] == main_clone, (
            f"Cleanup must target main_clone={main_clone}, got {args[0]!r}"
        )
        assert args[1] == fake_temp, f"Cleanup must target fake_temp={fake_temp}, got {args[1]!r}"

    @pytest.mark.asyncio
    async def test_review_pr_cleans_up_temp_checkout_on_reviewer_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin 3 / cell (e) — error-path variant: if the reviewer raises,
        cleanup still fires via the caller's ``finally`` block.
        """
        from unittest.mock import AsyncMock, MagicMock

        project_id = uuid.uuid4()
        fake_temp = tmp_path / "temp-checkout-286"
        fake_temp.mkdir()
        main_clone = tmp_path / "main-clone-286"
        _init_git_repo_at(main_clone)

        from src.gateway.review_engine import PrReviewRoot

        class _TempRootQueryCtx:
            async def __aenter__(self) -> object:
                stub = MagicMock()
                stub.find_by_branch = AsyncMock(return_value=None)
                stub.find_by_pr_url = AsyncMock(return_value=None)
                return stub

            async def __aexit__(self, *exc: object) -> bool:
                return False

        class _FailingLoop:
            def __init__(self, reviewer: object, **kwargs: object) -> None:
                self._stage = str(kwargs.get("stage", "?"))

            async def run(self, **_kwargs: object) -> object:
                raise RuntimeError("simulated reviewer crash")

        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-t281-e2",
            repo_full_name="sachinkundu/cloglog",
            pr_number=286,
            pr_url="https://github.com/sachinkundu/cloglog/pull/286",
            head_branch="wt-t281-temp",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": "e" * 40}}},
        )

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=MagicMock(),
        )

        temp_root = PrReviewRoot(path=fake_temp, is_temp=True, main_clone=main_clone)
        remove_mock = AsyncMock()
        monkeypatch.setattr("src.gateway.review_engine._remove_review_checkout", remove_mock)
        monkeypatch.setattr(
            "src.gateway.review_engine.resolve_pr_review_root",
            AsyncMock(return_value=temp_root),
        )

        with (
            patch(
                "src.gateway.review_engine.settings.opencode_enabled",
                False,
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            patch("src.gateway.review_loop.CodexReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.ReviewLoop", new=_FailingLoop),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value="diff")),
            patch.object(
                consumer,
                "_resolve_project_id",
                new=AsyncMock(return_value=project_id),
            ),
            patch.object(
                consumer,
                "_registry",
                new=lambda: TestReviewPrUsesWorktreeProjectRoot._RecordingRegistryCtx(),
            ),
            patch.object(consumer, "_worktree_query", new=lambda: _TempRootQueryCtx()),
            pytest.raises(RuntimeError, match="simulated reviewer crash"),
        ):
            await consumer._review_pr(event)

        remove_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# T-374: timeout scales with diff size + emits codex_review_timed_out event
# ---------------------------------------------------------------------------


class TestComputeReviewTimeout:
    """``compute_review_timeout`` scales the codex subprocess budget by diff size."""

    def test_empty_diff_returns_base_timeout(self) -> None:
        from src.gateway.review_engine import (
            REVIEW_TIMEOUT_BASE_SECONDS,
            compute_review_timeout,
        )

        lines, timeout = compute_review_timeout("")
        assert lines == 0
        assert timeout == REVIEW_TIMEOUT_BASE_SECONDS

    def test_small_diff_stays_at_base(self) -> None:
        """A 4-line diff should not exceed the base by much."""
        from src.gateway.review_engine import (
            REVIEW_TIMEOUT_BASE_SECONDS,
            REVIEW_TIMEOUT_PER_LINE_SECONDS,
            compute_review_timeout,
        )

        diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n-old1\n-old2\n+new1\n+new2\n"
        lines, timeout = compute_review_timeout(diff)
        assert lines == 4
        expected = REVIEW_TIMEOUT_BASE_SECONDS + 4 * REVIEW_TIMEOUT_PER_LINE_SECONDS
        assert timeout == expected

    def test_large_diff_scales(self) -> None:
        """A 1 000-line diff should produce a timeout above base + per_line*1000."""
        from src.gateway.review_engine import (
            REVIEW_TIMEOUT_BASE_SECONDS,
            REVIEW_TIMEOUT_CAP_SECONDS,
            REVIEW_TIMEOUT_PER_LINE_SECONDS,
            compute_review_timeout,
        )

        diff_lines = ["diff --git a/x b/x", "--- a/x", "+++ b/x", "@@ -1,1000 +1,1000 @@"]
        diff_lines += [f"+line {i}" for i in range(1000)]
        diff = "\n".join(diff_lines)

        lines, timeout = compute_review_timeout(diff)
        assert lines == 1000
        expected = min(
            REVIEW_TIMEOUT_CAP_SECONDS,
            REVIEW_TIMEOUT_BASE_SECONDS + 1000 * REVIEW_TIMEOUT_PER_LINE_SECONDS,
        )
        assert timeout == expected
        assert timeout > REVIEW_TIMEOUT_BASE_SECONDS

    def test_timeout_caps_at_max(self) -> None:
        """A diff whose linear timeout would exceed the cap clamps to the cap."""
        from src.gateway.review_engine import (
            REVIEW_TIMEOUT_CAP_SECONDS,
            compute_review_timeout,
        )

        diff_lines = ["diff --git a/x b/x", "--- a/x", "+++ b/x", "@@ -1,5000 +1,5000 @@"]
        diff_lines += [f"+line {i}" for i in range(5000)]
        diff = "\n".join(diff_lines)

        lines, timeout = compute_review_timeout(diff)
        assert lines == 5000
        assert timeout == REVIEW_TIMEOUT_CAP_SECONDS

    def test_file_headers_excluded_from_count(self) -> None:
        """``+++`` and ``---`` file headers must not inflate the changed-line count."""
        from src.gateway.review_engine import compute_review_timeout

        diff = (
            "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n"
            "diff --git a/b b/b\n--- a/b\n+++ b/b\n@@ -1 +1 @@\n-old\n+new\n"
        )
        lines, _ = compute_review_timeout(diff)
        assert lines == 4  # two -/+ pairs only — file headers excluded


class TestCodexReviewTimedOutEmission:
    """The post-retry timeout path emits a ``codex_review_timed_out`` inbox event."""

    @pytest.fixture(autouse=True)
    def _stubs(self) -> Any:
        with (
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
        ):
            yield

    @pytest.mark.asyncio
    async def test_emits_inbox_event_on_second_timeout(self, sample_diff: str) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            return _FakeProcess(hang=True)

        emit_mock = AsyncMock()
        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            # Force a tiny timeout so the test does not actually wait minutes.
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_BASE_SECONDS", 0.01),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_CAP_SECONDS", 0.01),
            patch("src.gateway.review_engine.emit_codex_review_timed_out", emit_mock),
            patch(
                "src.gateway.review_engine._probe_codex_alive",
                new=AsyncMock(return_value=(True, "ok")),
            ),
            patch(
                "src.gateway.review_engine._probe_github_reachable",
                new=AsyncMock(return_value=(True, "ok")),
            ),
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
            mock.post(_ISSUES_COMMENTS_URL).mock(return_value=httpx.Response(201, json={"id": 1}))
            await consumer.handle(_event())

        assert emit_mock.await_count == 1
        kwargs = emit_mock.await_args.kwargs
        assert kwargs["pr_url"] == "https://github.com/sachinkundu/cloglog/pull/42"
        assert kwargs["pr_number"] == 42
        assert kwargs["repo_full_name"] == "sachinkundu/cloglog"
        assert kwargs["diff_size"] >= 0
        assert kwargs["timeout_seconds"] > 0

    @pytest.mark.asyncio
    async def test_no_emission_when_first_attempt_succeeds(
        self, sample_diff: str, sample_review_json: str
    ) -> None:
        """A successful review must NOT emit a timeout event."""
        from src.gateway import review_engine as engine_mod

        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            pytest.fail("_spawn should only be called for gh")

        async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
            # Write parseable review.json into the -o output path
            # (mirrors the existing happy-path tests).
            for i, a in enumerate(args):
                if a == "-o" and i + 1 < len(args):
                    Path(args[i + 1]).write_text(sample_review_json)
                    break
            return _FakeProcess(stdout=b"")

        emit_mock = AsyncMock()
        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
            patch.object(engine_mod, "emit_codex_review_timed_out", emit_mock),
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
            mock.post(re.compile(r".*/pulls/\d+/reviews$")).mock(
                return_value=httpx.Response(201, json={"id": 1})
            )
            await consumer.handle(_event())

        assert emit_mock.await_count == 0


# ---------------------------------------------------------------------------
# T-374 codex round 1 HIGH — sequenced codex timeout posts AGENT_TIMEOUT skip
# ---------------------------------------------------------------------------


class TestSequencedCodexTimeoutSkipComment:
    """When the codex ReviewLoop ends with ``last_timed_out``, ``_review_pr``
    must post the same AGENT_TIMEOUT skip comment the legacy
    ``_run_review_agent`` path posts. Without this finalization, a sequenced
    codex timeout produces no PR-visible signal at all (only the inbox
    event), recreating the silent-timeout regression.
    """

    @pytest.mark.asyncio
    async def test_codex_loop_timeout_posts_agent_timeout_skip(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from src.agent.interfaces import WorktreeRow
        from src.gateway.review_engine import ReviewEngineConsumer
        from src.gateway.review_loop import LoopOutcome
        from src.gateway.review_skip_comments import SkipReason

        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-timeout"
        worktree_sha = _init_git_repo_at(worktree_dir)

        row = WorktreeRow(
            id=uuid.uuid4(),
            project_id=project_id,
            worktree_path=str(worktree_dir),
            branch_name="wt-timeout",
            status="online",
        )

        class _MatchingQueryCtx:
            async def __aenter__(self) -> object:
                stub = MagicMock()
                stub.find_by_branch = AsyncMock(return_value=row)
                stub.find_by_pr_url = AsyncMock(return_value=None)
                return stub

            async def __aexit__(self, *exc: object) -> bool:
                return False

        captured_loop_kwargs: dict[str, object] = {}

        class _TimingOutLoop:
            def __init__(self, _reviewer: object, **kwargs: object) -> None:
                # Snapshot ctor args so the test can verify head_branch
                # plumbing alongside the timeout-skip behaviour.
                captured_loop_kwargs.update(kwargs)
                self._stage = str(kwargs.get("stage", "?"))

            async def run(self, **_kwargs: object) -> LoopOutcome:
                outcome = LoopOutcome(
                    turns_used=2,
                    consensus_reached=False,
                    total_elapsed_seconds=1.0,
                )
                # Codex stage ended in timeout — populate the diagnostics
                # _review_pr's finalizer reads.
                if self._stage == "codex":
                    outcome.last_timed_out = True
                    outcome.last_timeout_diff_lines = 123
                    outcome.last_timeout_seconds = 555.0
                    outcome.last_timeout_stderr_excerpt = "fatal: codex hung"
                    outcome.last_timeout_elapsed_seconds = 555.5
                return outcome

        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-timeout",
            repo_full_name="sachinkundu/cloglog",
            pr_number=999,
            pr_url="https://github.com/sachinkundu/cloglog/pull/999",
            head_branch="wt-timeout",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": worktree_sha}}},
        )

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=MagicMock(),
        )

        post_skip_mock = AsyncMock()
        emit_mock = AsyncMock()
        with (
            patch(
                "src.gateway.review_engine.settings.opencode_enabled",
                False,
            ),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            patch(
                "src.gateway.review_engine._probe_codex_alive",
                new=AsyncMock(return_value=(True, "codex 0.1.0")),
            ),
            patch(
                "src.gateway.review_engine._probe_github_reachable",
                new=AsyncMock(return_value=(True, "200 ok")),
            ),
            patch("src.gateway.review_loop.CodexReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.ReviewLoop", new=_TimingOutLoop),
            patch("src.gateway.review_engine.emit_codex_review_timed_out", emit_mock),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value="diff")),
            patch.object(
                consumer,
                "_resolve_project_id",
                new=AsyncMock(return_value=project_id),
            ),
            patch.object(
                consumer,
                "_registry",
                new=lambda: TestReviewPrUsesWorktreeProjectRoot._RecordingRegistryCtx(),
            ),
            patch.object(consumer, "_worktree_query", new=lambda: _MatchingQueryCtx()),
            patch.object(consumer, "_post_agent_skip", new=post_skip_mock),
        ):
            await consumer._review_pr(event)

        # Skip comment posted with AGENT_TIMEOUT and the budget that was hit.
        assert post_skip_mock.await_count == 1
        call_args = post_skip_mock.await_args.args
        assert call_args[1] == SkipReason.AGENT_TIMEOUT
        body = call_args[2]
        assert "555s" in body
        assert "fatal: codex hung" in body

        # codex round 5 HIGH: supervisor event fires from the terminal
        # finalizer, not from inside ReviewLoop's per-turn branch.
        assert emit_mock.await_count == 1
        emit_kwargs = emit_mock.await_args.kwargs
        assert emit_kwargs["pr_number"] == 999
        assert emit_kwargs["diff_size"] == 123
        assert emit_kwargs["timeout_seconds"] == 555.0
        assert emit_kwargs["head_branch"] == "wt-timeout"

        # head_branch plumbing pin (codex round 1 CRITICAL fix): the
        # ReviewLoop still receives event.head_branch (kept on the
        # signature so a future fan-out variant can use it).
        assert captured_loop_kwargs.get("head_branch") == "wt-timeout"


class TestSequencedCodexNonTerminalTimeoutNoEmit:
    """Codex round 5 HIGH regression test: when ``codex_max_turns > 1``
    and turn 1 times out but turn 2 succeeds, ``_review_pr`` must NOT
    post AGENT_TIMEOUT and must NOT emit ``codex_review_timed_out``.
    """

    @pytest.mark.asyncio
    async def test_no_emit_when_turn1_timeout_turn2_succeeds(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from src.agent.interfaces import WorktreeRow
        from src.gateway.review_engine import ReviewEngineConsumer
        from src.gateway.review_loop import LoopOutcome

        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-nonterminal"
        worktree_sha = _init_git_repo_at(worktree_dir)
        row = WorktreeRow(
            id=uuid.uuid4(),
            project_id=project_id,
            worktree_path=str(worktree_dir),
            branch_name="wt-nonterminal",
            status="online",
        )

        class _MatchingQueryCtx:
            async def __aenter__(self) -> object:
                stub = MagicMock()
                stub.find_by_branch = AsyncMock(return_value=row)
                stub.find_by_pr_url = AsyncMock(return_value=None)
                return stub

            async def __aexit__(self, *exc: object) -> bool:
                return False

        class _ConvergedLoop:
            def __init__(self, _reviewer: object, **_kwargs: object) -> None:
                pass

            async def run(self, **_kwargs: object) -> LoopOutcome:
                # Stage ended in success; per-iteration reset cleared
                # the timeout flag from turn 1.
                return LoopOutcome(
                    turns_used=2,
                    consensus_reached=True,
                    total_elapsed_seconds=1.0,
                )

        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-nonterm",
            repo_full_name="sachinkundu/cloglog",
            pr_number=1000,
            pr_url="https://github.com/sachinkundu/cloglog/pull/1000",
            head_branch="wt-nonterminal",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": worktree_sha}}},
        )
        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=MagicMock(),
        )
        post_skip_mock = AsyncMock()
        emit_mock = AsyncMock()
        with (
            patch("src.gateway.review_engine.settings.opencode_enabled", False),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="claude-tok"),
            ),
            patch(
                "src.gateway.github_token.get_codex_reviewer_token",
                new=AsyncMock(return_value="codex-tok"),
            ),
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=0),
            ),
            patch("src.gateway.review_loop.CodexReviewer", new=MagicMock()),
            patch("src.gateway.review_loop.ReviewLoop", new=_ConvergedLoop),
            patch("src.gateway.review_engine.emit_codex_review_timed_out", emit_mock),
            patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value="diff")),
            patch.object(consumer, "_resolve_project_id", new=AsyncMock(return_value=project_id)),
            patch.object(
                consumer,
                "_registry",
                new=lambda: TestReviewPrUsesWorktreeProjectRoot._RecordingRegistryCtx(),
            ),
            patch.object(consumer, "_worktree_query", new=lambda: _MatchingQueryCtx()),
            patch.object(consumer, "_post_agent_skip", new=post_skip_mock),
        ):
            await consumer._review_pr(event)

        assert post_skip_mock.await_count == 0, (
            "A converging review (turn 1 timeout, turn 2 success) must NOT trigger "
            "the AGENT_TIMEOUT skip comment."
        )
        assert emit_mock.await_count == 0, (
            "A converging review must NOT emit codex_review_timed_out — emission "
            "is gated on the codex stage's terminal state."
        )
