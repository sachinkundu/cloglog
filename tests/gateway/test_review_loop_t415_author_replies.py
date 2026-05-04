"""T-415: Author thread replies wired into the Prior review history preamble.

Covers AC4:
(a) finding with one author reply — latest reply text appears.
(b) finding with multiple replies — latest (highest id) wins.
(c) finding with zero replies — ``Author response: (none)`` is rendered.

All tests use a stub registry and never make live GitHub calls.
``PriorTurnSummary.author_responses`` is populated either directly (render
tests) or via ``_build_enriched_turns`` with fake review/comment fixtures
(matching-logic tests).

Also covers the ``enrich_prior_context`` error-fallback path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.gateway.review_loop import _render_prior_history_section
from src.gateway.review_thread_replies import _build_enriched_turns, enrich_prior_context
from src.review.interfaces import PriorContext, PriorTurnSummary

_PR_URL = "https://github.com/owner/repo/pull/415"
_SHA_1 = "aabbccdd1122334455667788"
_SHA_2 = "11223344aabbccdd55667788"
_CODEX_BOT = "cloglog-codex-reviewer[bot]"
_AUTHOR = "pr-author"


# ---------------------------------------------------------------------------
# _render_prior_history_section — author response rendering (AC4 a/b/c)
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
        """AC4(a): one reply → its text is in the preamble."""
        ctx = self._make_ctx({"0": "Fixed in abc123, see commit."})
        out = _render_prior_history_section(ctx)
        assert "Author response: Fixed in abc123, see commit." in out

    def test_zero_replies_renders_none(self) -> None:
        """AC4(c): no reply → ``(none)``."""
        ctx = self._make_ctx({"0": None})
        out = _render_prior_history_section(ctx)
        assert "Author response: (none)" in out

    def test_absent_key_renders_none(self) -> None:
        """Missing key in author_responses also renders ``(none)``."""
        ctx = self._make_ctx({})
        out = _render_prior_history_section(ctx)
        assert "Author response: (none)" in out

    def test_not_fetched_placeholder_is_gone(self) -> None:
        """Regression pin — the old placeholder must never appear."""
        ctx = self._make_ctx({})
        out = _render_prior_history_section(ctx)
        assert "(not fetched)" not in out

    def test_multiple_findings_each_get_their_response(self) -> None:
        """AC4(b): each finding gets the right response keyed by index."""
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
                        "0": "won't fix — this is intentional",
                        "1": None,
                    },
                )
            ],
        )
        out = _render_prior_history_section(ctx)
        assert "Author response: won't fix — this is intentional" in out
        assert "Author response: (none)" in out


# ---------------------------------------------------------------------------
# _build_enriched_turns — reply matching logic (no network calls)
# ---------------------------------------------------------------------------


def _review(rid: int, sha: str, login: str = _CODEX_BOT) -> dict[str, Any]:
    return {"id": rid, "commit_id": sha, "user": {"login": login}}


def _root_comment(
    cid: int,
    review_id: int,
    path: str,
    line: int,
    login: str = _CODEX_BOT,
) -> dict[str, Any]:
    return {
        "id": cid,
        "pull_request_review_id": review_id,
        "path": path,
        "line": line,
        "body": f"**[HIGH]** finding at {path}:{line}",
        "user": {"login": login},
        "in_reply_to_id": None,
    }


def _reply(
    cid: int,
    root_id: int,
    body: str,
    login: str = _AUTHOR,
) -> dict[str, Any]:
    return {
        "id": cid,
        "body": body,
        "user": {"login": login},
        "in_reply_to_id": root_id,
    }


def _make_context(
    findings: list[dict[str, Any]],
    sha: str = _SHA_1,
    turn_number: int = 1,
) -> PriorContext:
    return PriorContext(
        pr_url=_PR_URL,
        turns=[
            PriorTurnSummary(
                head_sha=sha,
                turn_number=turn_number,
                findings=findings,
                learnings=[],
            )
        ],
    )


class TestBuildEnrichedTurns:
    def test_author_reply_mapped_to_finding(self) -> None:
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        reviews = [_review(101, _SHA_1)]
        comments = [
            _root_comment(1, 101, "src/foo.py", 10),
            _reply(2, 1, "Fixed in abc123."),
        ]
        [turn] = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn.author_responses["0"] == "Fixed in abc123."

    def test_multiple_replies_latest_wins(self) -> None:
        """AC4(b): latest author reply (highest comment ID) wins."""
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        reviews = [_review(101, _SHA_1)]
        comments = [
            _root_comment(1, 101, "src/foo.py", 10),
            _reply(2, 1, "first reply"),
            _reply(5, 1, "later reply"),
        ]
        [turn] = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn.author_responses["0"] == "later reply"

    def test_zero_replies_gives_none(self) -> None:
        """AC4(c): no reply → None."""
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        reviews = [_review(101, _SHA_1)]
        comments = [_root_comment(1, 101, "src/foo.py", 10)]
        [turn] = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn.author_responses["0"] is None

    def test_non_author_reply_excluded(self) -> None:
        """Teammate/maintainer replies are not shown as author response."""
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        reviews = [_review(101, _SHA_1)]
        comments = [
            _root_comment(1, 101, "src/foo.py", 10),
            _reply(2, 1, "teammate comment", login="other-dev"),
        ]
        [turn] = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn.author_responses["0"] is None

    def test_opencode_thread_at_same_location_excluded(self) -> None:
        """Reply to opencode comment at same (file, line) must not leak in."""
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        # review 101 = codex, review 200 = opencode (different bot)
        reviews = [_review(101, _SHA_1)]
        comments = [
            _root_comment(1, 101, "src/foo.py", 10),  # codex root (no reply)
            _root_comment(
                9, 200, "src/foo.py", 10, login="cloglog-opencode-reviewer[bot]"
            ),  # opencode root
            _reply(10, 9, "replied to opencode, not codex"),  # reply to opencode
        ]
        [turn] = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn.author_responses["0"] is None

    def test_cross_commit_isolation(self) -> None:
        """Reply to commit-A finding must not appear under commit-B re-filing."""
        ctx = PriorContext(
            pr_url=_PR_URL,
            turns=[
                PriorTurnSummary(
                    head_sha=_SHA_1,
                    turn_number=1,
                    findings=[{"file": "src/foo.py", "line": 10}],
                    learnings=[],
                ),
                PriorTurnSummary(
                    head_sha=_SHA_2,
                    turn_number=2,
                    findings=[{"file": "src/foo.py", "line": 10}],
                    learnings=[],
                ),
            ],
        )
        # review 101 on SHA_1 has a reply; review 102 on SHA_2 has no reply
        reviews = [_review(101, _SHA_1), _review(102, _SHA_2)]
        comments = [
            _root_comment(1, 101, "src/foo.py", 10),
            _reply(2, 1, "Fixed in sha1 commit"),
            _root_comment(3, 102, "src/foo.py", 10),  # no reply here
        ]
        turn1, turn2 = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn1.author_responses["0"] == "Fixed in sha1 commit"
        assert turn2.author_responses["0"] is None

    def test_two_codex_turns_same_sha(self) -> None:
        """Two codex turns on the same SHA map to their own reviews."""
        ctx = PriorContext(
            pr_url=_PR_URL,
            turns=[
                PriorTurnSummary(
                    head_sha=_SHA_1,
                    turn_number=1,
                    findings=[{"file": "src/a.py", "line": 1}],
                    learnings=[],
                ),
                PriorTurnSummary(
                    head_sha=_SHA_1,
                    turn_number=2,
                    findings=[{"file": "src/b.py", "line": 2}],
                    learnings=[],
                ),
            ],
        )
        # Two codex reviews on SHA_1 (ids 101 < 102 → first=turn1, second=turn2)
        reviews = [_review(101, _SHA_1), _review(102, _SHA_1)]
        comments = [
            _root_comment(1, 101, "src/a.py", 1),
            _reply(2, 1, "turn1 reply"),
            _root_comment(3, 102, "src/b.py", 2),
            # no reply for turn2
        ]
        turn1, turn2 = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn1.author_responses["0"] == "turn1 reply"
        assert turn2.author_responses["0"] is None

    def test_no_codex_review_found_gives_empty_responses(self) -> None:
        """When no codex review matches a turn, responses dict is empty."""
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        [turn] = _build_enriched_turns(ctx, [], [], _AUTHOR)
        assert turn.author_responses == {}

    def test_review_count_mismatch_returns_none_not_misattributed(self) -> None:
        """When review count > turn count on a SHA (db_error path dropped a turn),
        position-based matching is unsafe — return None rather than misattribute."""
        # SHA_1 has 2 codex reviews (turn 1 posted but findings not persisted,
        # so only turn 2 is in PriorContext). Position would wrongly map turn 2
        # to review 101 (turn 1's review). The fix: detect mismatch → None.
        ctx = _make_context([{"file": "src/foo.py", "line": 10}], sha=_SHA_1, turn_number=2)
        reviews = [_review(101, _SHA_1), _review(102, _SHA_1)]  # 2 reviews, 1 turn
        comments = [
            _root_comment(1, 101, "src/foo.py", 10),
            _reply(2, 1, "reply to turn-1 thread — must NOT appear on turn-2"),
            _root_comment(3, 102, "src/foo.py", 10),  # turn 2's real root, no reply
        ]
        [turn] = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        assert turn.author_responses == {}

    def test_original_line_fallback(self) -> None:
        """Comments on outdated commits use ``original_line`` instead of ``line``."""
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        root: dict[str, Any] = {
            "id": 1,
            "pull_request_review_id": 101,
            "path": "src/foo.py",
            "original_line": 10,
            "body": "bot comment",
            "user": {"login": _CODEX_BOT},
            "in_reply_to_id": None,
        }
        rep = _reply(2, 1, "author reply using original_line")
        [turn] = _build_enriched_turns(ctx, [_review(101, _SHA_1)], [root, rep], _AUTHOR)
        assert turn.author_responses["0"] == "author reply using original_line"

    def test_reply_truncated_at_500_chars(self) -> None:
        long_body = "x" * 600
        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        reviews = [_review(101, _SHA_1)]
        comments = [
            _root_comment(1, 101, "src/foo.py", 10),
            _reply(2, 1, long_body),
        ]
        [turn] = _build_enriched_turns(ctx, reviews, comments, _AUTHOR)
        val = turn.author_responses["0"]
        assert val is not None
        assert len(val) <= 504  # 500 chars + " …"
        assert val.endswith(" …")


# ---------------------------------------------------------------------------
# enrich_prior_context — error-fallback path
# ---------------------------------------------------------------------------


class TestEnrichPriorContextErrorFallback:
    @pytest.mark.asyncio
    async def test_github_api_error_returns_original_context(self) -> None:
        """Any GitHub API failure must return the original context unchanged."""
        import httpx

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        ctx = _make_context([{"file": "src/foo.py", "line": 10}])
        result = await enrich_prior_context(
            "owner/repo", 1, ctx, _AUTHOR, "fake-token", client=mock_client
        )
        assert result is ctx  # same object, not a copy

    @pytest.mark.asyncio
    async def test_empty_turns_skips_api(self) -> None:
        """No GitHub call when prior_context has no turns."""
        import httpx

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        ctx = PriorContext(pr_url=_PR_URL, turns=[])
        result = await enrich_prior_context(
            "owner/repo", 1, ctx, _AUTHOR, "fake-token", client=mock_client
        )
        assert result is ctx
        mock_client.get.assert_not_called()
