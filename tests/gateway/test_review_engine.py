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
    count_bot_reviews,
    extract_diff_new_lines,
    filter_diff,
    is_review_agent_available,
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
        """When prior bot reviews == MAX_REVIEWS_PER_PR, posts a 'maximum' comment."""
        consumer = ReviewEngineConsumer(max_per_hour=10)
        with (
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=MAX_REVIEWS_PER_PR),
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
        assert "maximum" in body_lower or str(MAX_REVIEWS_PER_PR) in payload["body"]

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
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_SECONDS", 0.01),
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
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_SECONDS", 0.01),
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
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_SECONDS", 0.01),
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
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_SECONDS", 0.01),
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
            from unittest.mock import MagicMock

            return MagicMock()

        async def __aexit__(self, *exc: object) -> bool:
            return False

    class _NoopWorktreeQueryCtx:
        """Yields a stub ``IWorktreeQuery`` whose ``find_by_branch`` returns None,
        so ``resolve_pr_review_root`` falls through to the host-level root
        (``settings.review_source_root or Path.cwd()``) — the behaviour the
        pre-T-278 tests assumed.
        """

        async def __aenter__(self) -> object:
            from unittest.mock import AsyncMock, MagicMock

            stub = MagicMock()
            stub.find_by_branch = AsyncMock(return_value=None)
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

            async def run(self, *, diff: str) -> object:
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

    Holds one optional ``WorktreeRow`` and returns it for matching
    ``(project_id, branch_name)`` lookups. Lets the resolver tests run
    without a database — the DB path is covered independently in
    ``tests/agent/test_integration.py`` and the DDD pin test below.
    """

    def __init__(self, row: Any | None = None) -> None:
        self._row = row

    async def find_by_branch(self, project_id: Any, branch_name: str) -> Any:
        if self._row is None:
            return None
        if self._row.project_id != project_id:
            return None
        if self._row.branch_name != branch_name:
            return None
        return self._row


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
    """Per-PR review-root resolution — the worktree owning the PR wins over
    the host-level fallback. T-278.

    CLAUDE.md "``Path.cwd()`` in backend code is a filesystem fingerprint of
    the launcher, not an invariant" (T-255) is host-level; this test class
    pins the per-PR half of the same rule.
    """

    @staticmethod
    def _event_for_branch(
        head_branch: str, head_sha: str = "a" * 40, pr_number: int = 278
    ) -> WebhookEvent:
        return WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id=f"d-{pr_number}",
            repo_full_name="sachinkundu/cloglog",
            pr_number=pr_number,
            pr_url=f"https://github.com/sachinkundu/cloglog/pull/{pr_number}",
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
        """Matching worktree row + path exists → helper returns the worktree path."""
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

        assert result == worktree_dir, f"Expected worktree path {worktree_dir}, got {result}"
        # No fallback warning should fire on the happy path.
        fallback_warnings = [
            r for r in caplog.records if "review_source=fallback" in r.getMessage()
        ]
        assert fallback_warnings == [], (
            f"Happy path must not emit fallback warning; got {fallback_warnings}"
        )
        # No drift warning when SHAs match.
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
        """No worktree row → fallback to ``settings.review_source_root``; WARNING
        names ``reason=no_matching_worktree``.
        """
        import logging as _logging

        fallback_root = tmp_path / "host-fallback"
        fallback_root.mkdir()
        monkeypatch.setattr("src.gateway.review_engine.settings.review_source_root", fallback_root)
        query = _StubWorktreeQuery(None)
        event = self._event_for_branch("wt-unknown")

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=uuid.uuid4(), worktree_query=query
            )

        assert result == fallback_root, (
            f"No-match must fall back to settings.review_source_root; got {result}"
        )
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
        event = self._event_for_branch("wt-foo")

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=query
            )

        assert result == fallback_root, f"Expected fallback; got {result}"
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_source=fallback" in m and "reason=path_missing" in m for m in messages
        ), f"Missing path_missing WARNING; got {messages}"

    @pytest.mark.asyncio
    async def test_drift_warning_but_still_returns_worktree(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Worktree HEAD != event.head_sha → drift WARNING, worktree path still
        preferred. Per T-278: mid-rebase / unpushed commits are normal; a
        slightly-stale worktree still beats prod's main checkout.
        """
        import logging as _logging

        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-drift"
        worktree_sha = _init_git_repo_at(worktree_dir)
        # Build an event with a DIFFERENT SHA. Generate a fully-independent
        # hex string so the "different SHA" claim never collides with the
        # worktree's real SHA (per CLAUDE.md "Test Determinism" rule).
        event_sha = "b" * 40 if not worktree_sha.startswith("b") else "c" * 40
        assert worktree_sha != event_sha, "Test setup error: generated SHAs accidentally matched"
        row = self._row(project_id, "wt-drift", str(worktree_dir))
        query = _StubWorktreeQuery(row)
        event = self._event_for_branch("wt-drift", head_sha=event_sha)

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=query
            )

        assert result == worktree_dir, f"Drift must NOT demote to fallback; got {result}"
        drift_messages = [
            r.getMessage() for r in caplog.records if "review_source_drift" in r.getMessage()
        ]
        assert drift_messages, (
            f"Expected drift WARNING; got log records: {[r.getMessage() for r in caplog.records]}"
        )
        assert worktree_sha[:7] in drift_messages[0], (
            f"Drift log missing worktree short SHA; got {drift_messages[0]!r}"
        )
        assert event_sha[:7] in drift_messages[0], (
            f"Drift log missing event short SHA; got {drift_messages[0]!r}"
        )

    @pytest.mark.asyncio
    async def test_empty_head_branch_uses_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``event.head_branch == ''`` is pathological but not fatal; the
        helper must short-circuit to the fallback without querying the DB,
        mirroring the empty-branch guard in ``AgentRepository``."""
        import logging as _logging

        fallback_root = tmp_path / "host-fallback"
        fallback_root.mkdir()
        monkeypatch.setattr("src.gateway.review_engine.settings.review_source_root", fallback_root)
        # If ``find_by_branch`` is called, raise — proving the short-circuit.
        query = _StubWorktreeQuery(None)
        event = self._event_for_branch("")

        with caplog.at_level(_logging.WARNING, logger="src.gateway.review_engine"):
            result = await resolve_pr_review_root(
                event, project_id=uuid.uuid4(), worktree_query=query
            )

        assert result == fallback_root
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "review_source=fallback" in m and "reason=no_matching_worktree" in m for m in messages
        ), f"Empty head_branch must emit no_matching_worktree; got {messages}"


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
            from unittest.mock import MagicMock

            return MagicMock()

        async def __aexit__(self, *exc: object) -> bool:
            return False

    @pytest.mark.asyncio
    async def test_review_pr_passes_worktree_path_to_reviewer(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        project_id = uuid.uuid4()
        worktree_dir = tmp_path / "wt-t278"
        _init_git_repo_at(worktree_dir)

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

            async def run(self, *, diff: str) -> object:
                return type("Outcome", (), {"turns_used": 1, "errors": []})()

        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-t278",
            repo_full_name="sachinkundu/cloglog",
            pr_number=278,
            pr_url="https://github.com/sachinkundu/cloglog/pull/278",
            head_branch="wt-t278",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": "e" * 40}}},
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
