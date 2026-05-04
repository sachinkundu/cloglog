"""Fetch GitHub PR review-comment thread replies for prior-turn findings.

Used by the codex review sequencer to populate ``PriorTurnSummary.author_responses``
before rendering the "Prior review history" preamble. Author replies on the
inline review thread (e.g. "won't fix because X", "fixed in <sha>") let the
next codex turn decide whether a finding is still standing rather than
re-filing it blindly.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Max chars to include from an author reply in the preamble.
_REPLY_TRUNCATE = 500

# Bot logins whose comments are reviewer comments, not author responses.
_BOT_LOGINS: frozenset[str] = frozenset(
    {
        "cloglog-codex-reviewer[bot]",
        "cloglog-opencode-reviewer[bot]",
    }
)

_GITHUB_API = "https://api.github.com"
_REVIEW_COMMENTS_TIMEOUT = 10.0


async def _fetch_all_review_comments(
    repo_full_name: str,
    pr_number: int,
    token: str,
    client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """Return all PR review comments (inline comments on the diff), paginated."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{_GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/comments"
    params: dict[str, str | int] = {"per_page": 100}
    results: list[dict[str, Any]] = []
    while url:
        resp = await client.get(
            url, headers=headers, params=params, timeout=_REVIEW_COMMENTS_TIMEOUT
        )
        resp.raise_for_status()
        results.extend(resp.json())
        # Follow Link: <url>; rel="next" pagination.
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


def _build_responses(
    comments: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, str | None]:
    """Map each finding's ``file:line`` to the latest non-bot reply text.

    Algorithm:
    1. Index all bot comments by their GitHub comment ``id``, keyed also by
       ``(path, effective_line)`` so we can match a finding to its thread root.
    2. For each bot comment at ``(file, line)`` matching a finding, collect
       all comments whose ``in_reply_to_id`` equals that bot comment's id.
    3. Among those replies, filter out other bot comments; take the latest by
       ``id`` (GitHub comment IDs are monotonically increasing).
    4. Truncate to ``_REPLY_TRUNCATE`` chars and record under the finding key.

    ``effective_line`` uses ``line`` when present (review comment on a
    RIGHT-side line), falling back to ``original_line`` for comments whose
    commit has since been superseded. Both fields use 1-based line numbers
    matching the findings JSON.
    """
    # Build lookup: comment_id → comment dict (all bot comments)
    bot_comments_by_id: dict[int, dict[str, Any]] = {}
    # (path, line) → list of bot comment ids at that location
    bot_at: dict[tuple[str, int], list[int]] = {}

    for c in comments:
        login: str = (c.get("user") or {}).get("login", "")
        if login not in _BOT_LOGINS:
            continue
        cid: int = c["id"]
        path: str = c.get("path", "")
        line: int | None = c.get("line") or c.get("original_line")
        if line is None:
            continue
        bot_comments_by_id[cid] = c
        bot_at.setdefault((path, line), []).append(cid)

    # Build lookup: in_reply_to_id → list of non-bot reply comments
    replies_by_root: dict[int, list[dict[str, Any]]] = {}
    for c in comments:
        root_id: int | None = c.get("in_reply_to_id")
        if root_id is None:
            continue
        login = (c.get("user") or {}).get("login", "")
        if login in _BOT_LOGINS:
            continue
        replies_by_root.setdefault(root_id, []).append(c)

    result: dict[str, str | None] = {}
    for finding in findings:
        file_ = finding.get("file", "")
        line_ = finding.get("line")
        if not file_ or line_ is None:
            continue
        key = f"{file_}:{line_}"
        bot_ids = bot_at.get((file_, int(line_)), [])
        latest_reply: dict[str, Any] | None = None
        for bid in bot_ids:
            for reply in replies_by_root.get(bid, []):
                if latest_reply is None or reply["id"] > latest_reply["id"]:
                    latest_reply = reply
        if latest_reply is not None:
            body: str = latest_reply.get("body", "")
            if len(body) > _REPLY_TRUNCATE:
                body = body[:_REPLY_TRUNCATE] + " …"
            result[key] = body
        else:
            result[key] = None
    return result


async def fetch_author_replies_for_findings(
    repo_full_name: str,
    pr_number: int,
    findings: list[dict[str, Any]],
    token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str | None]:
    """Return ``{file:line -> latest_author_reply | None}`` for each finding.

    On any GitHub API error, logs a warning and returns an empty dict so the
    caller gracefully falls back to ``Author response: (none)`` for all
    findings — a GitHub hiccup must never break the review flow.
    """
    if not findings:
        return {}
    close_when_done = client is None
    http = client or httpx.AsyncClient()
    try:
        comments = await _fetch_all_review_comments(repo_full_name, pr_number, token, http)
        return _build_responses(comments, findings)
    except Exception as exc:
        logger.warning(
            "fetch_author_replies_for_findings: GitHub API error for %s#%d — %s",
            repo_full_name,
            pr_number,
            exc,
        )
        return {}
    finally:
        if close_when_done:
            await http.aclose()
