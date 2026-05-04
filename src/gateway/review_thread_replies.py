"""Fetch GitHub PR review-comment thread replies for prior-turn findings.

Enriches ``PriorTurnSummary.author_responses`` before the "Prior review history"
preamble is rendered for the next codex turn. Author replies on the inline review
thread ("won't fix", "fixed in <sha>") let codex decide whether a finding is still
standing rather than re-filing it blindly.

Design guarantees:
- Each ``PriorTurnSummary`` is matched to the specific GitHub review the codex bot
  posted for that turn. The match key is ``(head_sha, turn_number)`` — composite
  so cross-push turns that both happen to be turn 1 on their respective SHAs are
  never confused.
- Each finding is matched to its own root comment via the body format that
  ``_partition_findings`` writes (``"**[SEVERITY]** body"``). This lets two
  distinct findings at the same ``(path, line)`` within one turn carry separate
  author responses.
- Only replies from the PR author's login are accepted. Teammate or maintainer
  comments on the thread are not attributed to the author.
- Responses are keyed by finding index (``str(i)``), not by ``file:line``, so the
  renderer can look up the reply for finding i without ambiguity.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace as _dc_replace
from typing import Any

import httpx

from src.review.interfaces import PriorContext, PriorTurnSummary

logger = logging.getLogger(__name__)

_REPLY_TRUNCATE = 500
_CODEX_BOT_LOGIN = "cloglog-codex-reviewer[bot]"

_GITHUB_API = "https://api.github.com"
_REQUEST_TIMEOUT = 10.0


def _make_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _paginate(
    url: str,
    headers: dict[str, str],
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Fetch all pages from a GitHub list endpoint."""
    results: list[dict[str, Any]] = []
    params: dict[str, str | int] = {"per_page": 100}
    while url:
        resp = await client.get(url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        results.extend(resp.json())
        link = resp.headers.get("Link", "")
        next_url: str | None = None
        for part in link.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                break
        url = next_url  # type: ignore[assignment]
        params = {}
    return results


async def _fetch_data(
    repo_full_name: str,
    pr_number: int,
    token: str,
    client: httpx.AsyncClient,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch PR reviews and all inline review comments in parallel."""
    headers = _make_headers(token)
    base = _GITHUB_API
    reviews_url = f"{base}/repos/{repo_full_name}/pulls/{pr_number}/reviews"
    comments_url = f"{base}/repos/{repo_full_name}/pulls/{pr_number}/comments"
    return await asyncio.gather(
        _paginate(reviews_url, headers, client),
        _paginate(comments_url, headers, client),
    )


def _build_enriched_turns(
    prior_context: PriorContext,
    reviews: list[dict[str, Any]],
    all_comments: list[dict[str, Any]],
    pr_author_login: str,
) -> list[PriorTurnSummary]:
    """Return enriched copies of each turn with ``author_responses`` populated.

    Separated from I/O so unit tests can exercise the matching logic without
    live GitHub calls.
    """
    # Index codex reviews by head_sha in creation order (review id is monotonic).
    codex_reviews_by_sha: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        login = (review.get("user") or {}).get("login", "")
        if login == _CODEX_BOT_LOGIN:
            sha = review.get("commit_id", "")
            if sha:
                codex_reviews_by_sha.setdefault(sha, []).append(review)
    for sha in codex_reviews_by_sha:
        codex_reviews_by_sha[sha].sort(key=lambda r: r["id"])

    # Map each prior turn to the review ID it produced.
    # Composite key (head_sha, turn_number) avoids collisions when two pushes
    # both happen to produce turn 1 on their respective SHAs.
    turns_by_sha: dict[str, list[PriorTurnSummary]] = {}
    for turn in prior_context.turns:
        turns_by_sha.setdefault(turn.head_sha, []).append(turn)

    # Position-based matching is only safe when the review count equals the
    # replayed-turn count for a SHA. When they differ it means a turn posted a
    # GitHub review but its findings_json was never persisted (the db_error
    # path in review_loop.py swallows DBAPIError after mark_posted). In that
    # case enumerate() would assign the wrong review ID to every subsequent
    # turn on that SHA. The proper fix is to store github_review_id on the
    # pr_review_turns row; until that migration lands, return None for all
    # turns on the mismatched SHA so we degrade to "(none)" rather than
    # misattributing replies from an unrelated thread.
    turn_to_review_id: dict[tuple[str, int], int | None] = {}
    for sha, turns_on_sha in turns_by_sha.items():
        reviews_on_sha = codex_reviews_by_sha.get(sha, [])
        if len(reviews_on_sha) != len(turns_on_sha):
            for turn in turns_on_sha:
                turn_to_review_id[(sha, turn.turn_number)] = None
        else:
            for i, turn in enumerate(turns_on_sha):
                turn_to_review_id[(sha, turn.turn_number)] = reviews_on_sha[i]["id"]

    # Index all PR comments.
    # Root comments: keyed by (review_id, path, line) → list of (comment_id, body).
    # The body is stored so same-location findings can be matched to their own
    # root comment via the ``"**[SEVERITY]** body"`` format _partition_findings writes.
    # Reply comments: only from pr_author_login, keyed by root comment ID.
    roots_by_loc: dict[tuple[int, str, int], list[tuple[int, str]]] = {}
    author_replies_by_root: dict[int, list[dict[str, Any]]] = {}

    for c in all_comments:
        root_id: int | None = c.get("in_reply_to_id")
        if root_id is None:
            review_id = c.get("pull_request_review_id")
            path = c.get("path", "")
            line = c.get("line") or c.get("original_line")
            if review_id is not None and line is not None:
                loc_key = (int(review_id), path, int(line))
                roots_by_loc.setdefault(loc_key, []).append((c["id"], c.get("body", "")))
        else:
            login = (c.get("user") or {}).get("login", "")
            if login == pr_author_login:
                author_replies_by_root.setdefault(root_id, []).append(c)

    # Build responses per turn, keyed by finding index (str(idx)).
    enriched: list[PriorTurnSummary] = []
    for turn in prior_context.turns:
        review_id = turn_to_review_id.get((turn.head_sha, turn.turn_number))
        if review_id is None or not turn.findings:
            enriched.append(_dc_replace(turn, author_responses={}))
            continue

        responses: dict[str, str | None] = {}
        for idx, finding in enumerate(turn.findings):
            file_ = finding.get("file", "")
            line_ = finding.get("line")
            if not file_ or line_ is None:
                continue
            severity = finding.get("severity", "info")
            body_text = finding.get("body", "")
            expected_body = f"**[{severity.upper()}]** {body_text}"
            loc_key = (review_id, file_, int(line_))
            root_candidates = roots_by_loc.get(loc_key, [])
            # Match by body content to disambiguate same-location findings.
            # Fall back to the sole root when body matching fails (e.g. finding
            # has no severity/body fields in test fixtures).
            matched_root_id: int | None = None
            for root_cid, root_body in root_candidates:
                if root_body == expected_body:
                    matched_root_id = root_cid
                    break
            if matched_root_id is None and len(root_candidates) == 1:
                matched_root_id = root_candidates[0][0]
            latest_reply: dict[str, Any] | None = None
            if matched_root_id is not None:
                for reply in author_replies_by_root.get(matched_root_id, []):
                    if latest_reply is None or reply["id"] > latest_reply["id"]:
                        latest_reply = reply
            if latest_reply is not None:
                body: str = latest_reply.get("body", "")
                if len(body) > _REPLY_TRUNCATE:
                    body = body[:_REPLY_TRUNCATE] + " …"
                responses[str(idx)] = body
            else:
                responses[str(idx)] = None
        enriched.append(_dc_replace(turn, author_responses=responses))

    return enriched


async def enrich_prior_context(
    repo_full_name: str,
    pr_number: int,
    prior_context: PriorContext,
    pr_author_login: str,
    token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> PriorContext:
    """Return a copy of ``prior_context`` with ``author_responses`` populated.

    On any GitHub API error, logs a warning and returns the original
    ``prior_context`` unchanged — a network hiccup must never break the review
    flow.
    """
    if not prior_context.turns:
        return prior_context
    close_when_done = client is None
    http = client or httpx.AsyncClient()
    try:
        reviews, all_comments = await _fetch_data(repo_full_name, pr_number, token, http)
        enriched_turns = _build_enriched_turns(
            prior_context, reviews, all_comments, pr_author_login
        )
        return PriorContext(pr_url=prior_context.pr_url, turns=enriched_turns)
    except Exception as exc:
        logger.warning(
            "enrich_prior_context: GitHub API error for %s#%d — %s",
            repo_full_name,
            pr_number,
            exc,
        )
        return prior_context
    finally:
        if close_when_done:
            await http.aclose()
