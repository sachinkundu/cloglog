"""Skip-comment helper for the F-36 review engine.

When the review pipeline short-circuits a PR (rate limit, cap reached,
oversize diff, codex failure, timeout, etc.) it MUST leave a trail the
author can see. Silent skips erode trust in the bot — see PR #149 (timeout,
silent for hours) and PR #159 (codex exit 1, silent).

This module exposes ``post_skip_comment`` which writes an issue-style
comment on the PR as the Codex reviewer bot. To avoid spamming a PR that
repeatedly hits the same short-circuit (e.g., rate-limit during a burst),
the poster suppresses identical ``(repo, pr, reason)`` tuples within a
rolling hour. The suppression cache is in-memory; a backend restart
clears it, which is acceptable — worst case the author sees one extra
skip comment after a deploy.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

import httpx

logger = logging.getLogger(__name__)

_COMMENT_REPEAT_WINDOW_SECONDS: Final = 3600.0
_COMMENT_POST_TIMEOUT_SECONDS: Final = 30.0


class SkipReason(StrEnum):
    """Every reason the review pipeline might short-circuit a PR.

    Used as the dedupe key for repeat-suppression. A new reason MUST get
    a new enum value so the comment cache treats it as distinct.
    """

    RATE_LIMIT = "rate_limit"
    MAX_REVIEWS = "max_reviews"
    NO_REVIEWABLE_FILES = "no_reviewable_files"
    DIFF_TOO_LARGE = "diff_too_large"
    AGENT_UNPARSEABLE = "agent_unparseable"
    AGENT_TIMEOUT = "agent_timeout"


@dataclass
class _SkipCommentCache:
    """In-memory repeat-suppression cache keyed by (repo, pr, reason)."""

    _last_posted: dict[tuple[str, int, SkipReason], float] = field(default_factory=dict)

    def should_post(self, repo: str, pr: int, reason: SkipReason) -> bool:
        """Return True iff this (repo, pr, reason) has not posted within the window.

        Records the new attempt on True so back-to-back callers see False
        until the window rolls.
        """
        key = (repo, pr, reason)
        now = time.monotonic()
        ts = self._last_posted.get(key)
        if ts is not None and (now - ts) < _COMMENT_REPEAT_WINDOW_SECONDS:
            return False
        self._last_posted[key] = now
        return True

    def reset(self) -> None:
        self._last_posted.clear()


_cache = _SkipCommentCache()


async def post_skip_comment(
    repo_full_name: str,
    pr_number: int,
    reason: SkipReason,
    body: str,
    token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Post a skip notification as an issue comment on the PR.

    Returns ``True`` on successful post, ``False`` on suppression (repeat
    within the window) or on HTTP failure. Callers treat ``False`` as
    informational — the short-circuit proceeds regardless.
    """
    if not _cache.should_post(repo_full_name, pr_number, reason):
        logger.debug(
            "Skip comment suppressed (repeat within %.0fs): pr=%d reason=%s",
            _COMMENT_REPEAT_WINDOW_SECONDS,
            pr_number,
            reason.value,
        )
        return False

    url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"body": body}

    close_when_done = client is None
    http = client or httpx.AsyncClient()
    try:
        resp = await http.post(
            url,
            headers=headers,
            json=payload,
            timeout=_COMMENT_POST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return True
    except (httpx.HTTPError, httpx.HTTPStatusError) as err:
        logger.warning(
            "Skip comment post failed for PR #%d (reason=%s): %s",
            pr_number,
            reason.value,
            err,
        )
        return False
    finally:
        if close_when_done:
            await http.aclose()


def reset_skip_comment_cache() -> None:
    """Clear the in-memory repeat-suppression cache. For tests and session boundaries."""
    _cache.reset()
