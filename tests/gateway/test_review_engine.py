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
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from pydantic import ValidationError

from src.gateway.review_engine import (
    BOT_USERNAME,
    MAX_DIFF_CHARS,
    RATE_LIMIT_WINDOW_SECONDS,
    RateLimiter,
    ReviewEngineConsumer,
    ReviewFinding,
    ReviewResult,
    _format_review_body,
    _partition_findings,
    build_review_prompt,
    extract_diff_new_lines,
    filter_diff,
    is_review_agent_available,
    parse_review_output,
    post_review,
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
# build_review_prompt
# ---------------------------------------------------------------------------


def test_build_review_prompt_substitutes_diff_and_output() -> None:
    prompt = build_review_prompt("DIFF_CONTENT", Path("/tmp/out.json"))
    assert "DIFF_CONTENT" in prompt
    assert "/tmp/out.json" in prompt
    assert "Review this pull request diff" in prompt


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

    def test_self_review_guard_blocks_bot_sender(self) -> None:
        """PR_OPENED by the bot itself must be skipped to avoid feedback loops."""
        consumer = ReviewEngineConsumer()
        event = _event(WebhookEventType.PR_OPENED, sender=BOT_USERNAME)
        assert consumer.handles(event) is False


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

    async def communicate(self) -> tuple[bytes, bytes]:
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
            agent_proc = _FakeProcess(returncode=0)
            calls: list[tuple[str, ...]] = []
            output_path_holder: dict[str, Path] = {}

            async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
                calls.append(argv)
                if argv[0] == "gh":
                    return diff_proc
                # Agent invocation: find --prompt path, read it to extract output_path
                prompt_idx = argv.index("--prompt") + 1
                prompt_file = Path(argv[prompt_idx])
                prompt_text = prompt_file.read_text()
                # Extract the output path from the templated prompt
                for token in prompt_text.split():
                    if token.endswith("review.json"):
                        output_path = Path(token)
                        output_path.write_text(sample_review_json)
                        output_path_holder["path"] = output_path
                        break
                return agent_proc

            return _fake_spawn, calls, output_path_holder

        fake_spawn, calls, paths = fake_spawn_factory(sample_diff.encode())

        with (
            patch("src.gateway.review_engine._spawn", side_effect=fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
                new=AsyncMock(return_value="ghs_test"),
            ),
            patch(
                "src.gateway.review_engine.post_review",
                new=AsyncMock(return_value=True),
            ) as posted,
        ):
            await consumer.handle(_event())

        # Two spawns: gh pr diff + the review agent
        assert len(calls) == 2
        assert calls[0][:3] == ("gh", "pr", "diff")
        assert calls[1][0] == "codex"
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
            return agent_proc

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch("src.gateway.review_engine.REVIEW_TIMEOUT_SECONDS", 0.01),
            patch(
                "src.gateway.github_token.get_github_app_token",
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
        ):
            # Should complete without raising
            await consumer.handle(_event())

    @pytest.mark.asyncio
    async def test_unparseable_output_returns_none(self, sample_diff: str) -> None:
        consumer = ReviewEngineConsumer(max_per_hour=10)

        async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
            if argv[0] == "gh":
                return _FakeProcess(stdout=sample_diff.encode())
            # Locate the prompt path and write garbage to the promised review.json
            prompt_idx = argv.index("--prompt") + 1
            prompt_text = Path(argv[prompt_idx]).read_text()
            for tok in prompt_text.split():
                if tok.endswith("review.json"):
                    Path(tok).write_text("NOT JSON")
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
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
            # Write an empty-approve review.json so the consumer succeeds cleanly
            prompt_idx = argv.index("--prompt") + 1
            prompt_text = Path(argv[prompt_idx]).read_text()
            for tok in prompt_text.split():
                if tok.endswith("review.json"):
                    Path(tok).write_text(
                        json.dumps({"verdict": "approve", "summary": "ok", "findings": []})
                    )
                    break
            return _FakeProcess(returncode=0)

        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
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
        assert "Automated Review (Codex)" in body
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
        assert payload["event"] == "REQUEST_CHANGES"
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
    async def test_verdict_maps_to_github_event(self) -> None:
        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        for verdict, gh_event in (
            ("approve", "APPROVE"),
            ("request_changes", "REQUEST_CHANGES"),
            ("comment", "COMMENT"),
        ):
            result = ReviewResult(verdict=verdict, summary="x", findings=[])
            with respx.mock() as mock:
                route = mock.post(url).mock(return_value=httpx.Response(200, json={"id": 1}))
                await post_review("sachinkundu/cloglog", 42, result, _SAMPLE_DIFF_WITH_LINE, "t")
                payload = json.loads(route.calls.last.request.content)
                assert payload["event"] == gh_event


# ---------------------------------------------------------------------------
# Integration test — full flow with subprocess and GitHub both mocked (T-193)
# ---------------------------------------------------------------------------


class TestFullFlowIntegration:
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
            prompt_idx = argv.index("--prompt") + 1
            prompt_text = Path(argv[prompt_idx]).read_text()
            for tok in prompt_text.split():
                if tok.endswith("review.json"):
                    Path(tok).write_text(review_json)
                    break
            return _FakeProcess(returncode=0)

        url = "https://api.github.com/repos/sachinkundu/cloglog/pulls/42/reviews"
        with (
            patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
            patch(
                "src.gateway.github_token.get_github_app_token",
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
