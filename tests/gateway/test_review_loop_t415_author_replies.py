"""T-415: Author thread replies wired into the Prior review history preamble.

Covers AC4:
(a) finding with one author reply — latest reply text appears.
(b) finding with multiple replies — latest (highest id) wins.
(c) finding with zero replies — ``Author response: (none)`` is rendered.

All tests use a stub registry and never make live GitHub calls.
The ``PriorTurnSummary.author_responses`` dict is populated directly in the
test, mirroring what ``fetch_author_replies_for_findings`` would produce.

Also covers ``_build_responses`` logic (unit tests for the helper) and the
``fetch_author_replies_for_findings`` error-fallback path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.gateway.review_loop import _render_prior_history_section
from src.gateway.review_thread_replies import _build_responses
from src.review.interfaces import PriorContext, PriorTurnSummary

_PR_URL = "https://github.com/owner/repo/pull/415"
_SHA_1 = "aabbccdd1122334455667788"


# ---------------------------------------------------------------------------
# _render_prior_history_section — author response rendering
# ---------------------------------------------------------------------------


class TestRenderAuthorResponses:
    def _make_ctx(self, author_responses: dict[str, str | None]) -> PriorContext:
        return PriorContext(
            pr_url=_PR_URL,
            turns=[
                PriorTurnSummary(
                    head_sha=_SHA_1,
                    turn_number=1,
                    findings=[
                        {
                            "file": "src/foo.py",
                            "line": 10,
                            "severity": "high",
                            "body": "missing null check",
                            "title": "missing null check",
                        }
                    ],
                    learnings=[],
                    author_responses=author_responses,
                )
            ],
        )

    def test_one_author_reply_appears_in_output(self) -> None:
        ctx = self._make_ctx({"src/foo.py:10": "Fixed in abc123, see commit."})
        out = _render_prior_history_section(ctx)
        assert "Author response: Fixed in abc123, see commit." in out

    def test_zero_replies_renders_none(self) -> None:
        ctx = self._make_ctx({"src/foo.py:10": None})
        out = _render_prior_history_section(ctx)
        assert "Author response: (none)" in out

    def test_absent_key_renders_none(self) -> None:
        ctx = self._make_ctx({})
        out = _render_prior_history_section(ctx)
        assert "Author response: (none)" in out

    def test_not_fetched_placeholder_is_gone(self) -> None:
        """The old placeholder must never appear — T-415 replaced it."""
        ctx = self._make_ctx({})
        out = _render_prior_history_section(ctx)
        assert "(not fetched)" not in out

    def test_multiple_findings_each_get_their_response(self) -> None:
        ctx = PriorContext(
            pr_url=_PR_URL,
            turns=[
                PriorTurnSummary(
                    head_sha=_SHA_1,
                    turn_number=1,
                    findings=[
                        {
                            "file": "src/a.py",
                            "line": 1,
                            "severity": "high",
                            "body": "A",
                            "title": "A",
                        },
                        {
                            "file": "src/b.py",
                            "line": 2,
                            "severity": "low",
                            "body": "B",
                            "title": "B",
                        },
                    ],
                    learnings=[],
                    author_responses={
                        "src/a.py:1": "won't fix — this is intentional",
                        "src/b.py:2": None,
                    },
                )
            ],
        )
        out = _render_prior_history_section(ctx)
        assert "Author response: won't fix — this is intentional" in out
        assert "Author response: (none)" in out


# ---------------------------------------------------------------------------
# _build_responses — unit tests for the helper logic (no network calls)
# ---------------------------------------------------------------------------


def _make_comment(
    cid: int,
    path: str,
    line: int,
    login: str,
    body: str,
    in_reply_to_id: int | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "path": path,
        "line": line,
        "body": body,
        "user": {"login": login},
        "in_reply_to_id": in_reply_to_id,
    }


class TestBuildResponses:
    def test_one_reply_mapped_to_finding(self) -> None:
        comments = [
            _make_comment(
                1, "src/foo.py", 10, "cloglog-codex-reviewer[bot]", "**[HIGH]** missing null check"
            ),
            _make_comment(2, "src/foo.py", 10, "human-user", "Fixed in abc123.", in_reply_to_id=1),
        ]
        findings = [{"file": "src/foo.py", "line": 10}]
        result = _build_responses(comments, findings)
        assert result["src/foo.py:10"] == "Fixed in abc123."

    def test_multiple_replies_latest_wins(self) -> None:
        comments = [
            _make_comment(1, "src/foo.py", 10, "cloglog-codex-reviewer[bot]", "bot comment"),
            _make_comment(2, "src/foo.py", 10, "alice", "first reply", in_reply_to_id=1),
            _make_comment(5, "src/foo.py", 10, "bob", "later reply", in_reply_to_id=1),
        ]
        findings = [{"file": "src/foo.py", "line": 10}]
        result = _build_responses(comments, findings)
        assert result["src/foo.py:10"] == "later reply"

    def test_zero_replies_gives_none(self) -> None:
        comments = [
            _make_comment(1, "src/foo.py", 10, "cloglog-codex-reviewer[bot]", "bot comment"),
        ]
        findings = [{"file": "src/foo.py", "line": 10}]
        result = _build_responses(comments, findings)
        assert result["src/foo.py:10"] is None

    def test_bot_reply_is_excluded(self) -> None:
        comments = [
            _make_comment(1, "src/foo.py", 10, "cloglog-codex-reviewer[bot]", "root"),
            _make_comment(
                2,
                "src/foo.py",
                10,
                "cloglog-opencode-reviewer[bot]",
                "bot reply",
                in_reply_to_id=1,
            ),
        ]
        findings = [{"file": "src/foo.py", "line": 10}]
        result = _build_responses(comments, findings)
        assert result["src/foo.py:10"] is None

    def test_original_line_fallback(self) -> None:
        """Comments on outdated commits use original_line instead of line."""
        comment: dict[str, Any] = {
            "id": 1,
            "path": "src/foo.py",
            "original_line": 10,
            "body": "bot comment",
            "user": {"login": "cloglog-codex-reviewer[bot]"},
            "in_reply_to_id": None,
        }
        reply: dict[str, Any] = {
            "id": 2,
            "path": "src/foo.py",
            "original_line": 10,
            "body": "author reply",
            "user": {"login": "author"},
            "in_reply_to_id": 1,
        }
        findings = [{"file": "src/foo.py", "line": 10}]
        result = _build_responses([comment, reply], findings)
        assert result["src/foo.py:10"] == "author reply"

    def test_reply_truncated_at_500_chars(self) -> None:
        long_body = "x" * 600
        comments = [
            _make_comment(1, "src/foo.py", 10, "cloglog-codex-reviewer[bot]", "root"),
            _make_comment(2, "src/foo.py", 10, "author", long_body, in_reply_to_id=1),
        ]
        findings = [{"file": "src/foo.py", "line": 10}]
        result = _build_responses(comments, findings)
        val = result["src/foo.py:10"]
        assert val is not None
        assert len(val) <= 504  # 500 chars + " …"
        assert val.endswith(" …")

    def test_empty_findings_returns_empty(self) -> None:
        comments = [_make_comment(1, "src/foo.py", 10, "cloglog-codex-reviewer[bot]", "root")]
        assert _build_responses(comments, []) == {}

    def test_no_matching_bot_comment_returns_none(self) -> None:
        """Finding at (file, line) with no bot comment at that location."""
        comments = [
            _make_comment(1, "src/other.py", 99, "cloglog-codex-reviewer[bot]", "root"),
        ]
        findings = [{"file": "src/foo.py", "line": 10}]
        result = _build_responses(comments, findings)
        assert result["src/foo.py:10"] is None


# ---------------------------------------------------------------------------
# fetch_author_replies_for_findings — error-fallback path
# ---------------------------------------------------------------------------


class TestFetchAuthorRepliesErrorFallback:
    @pytest.mark.asyncio
    async def test_github_api_error_returns_empty(self) -> None:
        """Any GitHub API failure must not raise — returns {} gracefully."""
        import httpx

        from src.gateway.review_thread_replies import fetch_author_replies_for_findings

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        findings = [{"file": "src/foo.py", "line": 10}]
        result = await fetch_author_replies_for_findings(
            "owner/repo", 1, findings, "fake-token", client=mock_client
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_findings_skips_api(self) -> None:
        """No GitHub call when findings list is empty."""
        import httpx

        from src.gateway.review_thread_replies import fetch_author_replies_for_findings

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        result = await fetch_author_replies_for_findings(
            "owner/repo", 1, [], "fake-token", client=mock_client
        )
        assert result == {}
        mock_client.get.assert_not_called()
