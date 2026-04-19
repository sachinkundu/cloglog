"""Demo driver: hit each of the six skip sites, assert the bot would POST a
comment in prod. Deterministic output — prints one line per reason plus a
terminal OK/FAIL.

Run under `uv run`; the demo-script captures this stdout via showboat exec.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import respx

from src.gateway.review_engine import (
    MAX_DIFF_CHARS,
    MAX_REVIEWS_PER_PR,
    ReviewEngineConsumer,
)
from src.gateway.review_skip_comments import reset_skip_comment_cache
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType

_REPO = "demo/repo"
_COMMENTS_URL = f"https://api.github.com/repos/{_REPO}/issues/"


def _event(pr: int) -> WebhookEvent:
    return WebhookEvent(
        type=WebhookEventType.PR_OPENED,
        delivery_id=f"d-{pr}",
        repo_full_name=_REPO,
        pr_number=pr,
        pr_url=f"https://github.com/{_REPO}/pull/{pr}",
        head_branch="wt-demo",
        base_branch="main",
        sender="demo-user",
        raw={},
    )


class _FakeProcess:
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

        class _S:
            def __init__(self, data: bytes) -> None:
                self._d = data

            async def read(self, n: int = -1) -> bytes:
                out, self._d = self._d, b""
                return out

        self.stderr = _S(stderr)

    def kill(self) -> None:
        self.kill_calls += 1
        self._hang = False

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:  # noqa: A002
        if self._hang:
            await asyncio.sleep(3600)
        return self._stdout, self._stderr

    async def wait(self) -> int:
        return self.returncode


async def _exercise_reason(reason: str, pr: int) -> int:
    """Drive `consumer.handle` through one skip branch; return comment-POST count."""
    reset_skip_comment_cache()

    url_pattern = f"{_COMMENTS_URL}{pr}/comments"
    base_patches = [
        patch(
            "src.gateway.github_token.get_github_app_token",
            new=AsyncMock(return_value="ghs_demo"),
        ),
        patch(
            "src.gateway.github_token.get_codex_reviewer_token",
            new=AsyncMock(return_value="ghs_demo"),
        ),
        patch(
            "src.gateway.review_engine.count_bot_reviews",
            new=AsyncMock(return_value=0),
        ),
    ]

    if reason == "rate_limit":
        consumer = ReviewEngineConsumer(max_per_hour=0)
    else:
        consumer = ReviewEngineConsumer(max_per_hour=10)

    if reason == "max_reviews":
        base_patches.append(
            patch(
                "src.gateway.review_engine.count_bot_reviews",
                new=AsyncMock(return_value=MAX_REVIEWS_PER_PR),
            )
        )

    sample_diff = (
        b"diff --git a/src/x.py b/src/x.py\n"
        b"--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    lockfile_diff = (
        b"diff --git a/package-lock.json b/package-lock.json\n"
        b"--- a/package-lock.json\n+++ b/package-lock.json\n@@ -1 +1 @@\n-x\n+y\n"
    )
    big = b"x" * (MAX_DIFF_CHARS + 100)
    huge_diff = (
        b"diff --git a/src/big.py b/src/big.py\n"
        b"--- a/src/big.py\n+++ b/src/big.py\n@@ -1 +1 @@\n-" + big + b"\n+" + big + b"\n"
    )

    if reason == "no_reviewable_files":
        diff_bytes = lockfile_diff
    elif reason == "diff_too_large":
        diff_bytes = huge_diff
    else:
        diff_bytes = sample_diff

    async def _fake_spawn(*argv: str, **kwargs: Any) -> _FakeProcess:
        if argv[0] == "gh":
            return _FakeProcess(stdout=diff_bytes)
        return _FakeProcess(stdout=b"", stderr=b"demo stderr", returncode=1)

    async def _fake_create(*args: Any, **kwargs: Any) -> _FakeProcess:
        if reason == "agent_timeout":
            return _FakeProcess(hang=True, stderr=b"demo timeout stderr")
        for i, arg in enumerate(args):
            if arg == "-o" and i + 1 < len(args):
                Path(args[i + 1]).write_text("NOT JSON")
                break
        return _FakeProcess(returncode=1, stderr=b"demo unparseable stderr")

    base_patches += [
        patch("src.gateway.review_engine._spawn", side_effect=_fake_spawn),
        patch("src.gateway.review_engine._create_subprocess", side_effect=_fake_create),
        patch(
            "src.gateway.review_engine._probe_codex_alive",
            new=AsyncMock(return_value=(True, "codex 1.0.0")),
        ),
        patch(
            "src.gateway.review_engine._probe_github_reachable",
            new=AsyncMock(return_value=(True, "200 zen")),
        ),
        patch("src.gateway.review_engine.REVIEW_TIMEOUT_SECONDS", 0.01),
    ]

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(url_pattern).mock(return_value=httpx.Response(201, json={"id": 1}))
        # Stub the reviews endpoint too so a happy-path bug would surface as a
        # non-zero call_count here; we never expect this in a skip-only demo.
        mock.post(f"https://api.github.com/repos/{_REPO}/pulls/{pr}/reviews").mock(
            return_value=httpx.Response(200, json={"id": 99})
        )
        for p in base_patches:
            p.start()
        try:
            await consumer.handle(_event(pr))
        finally:
            for p in base_patches:
                p.stop()
        return route.call_count


async def _main() -> int:
    reasons = [
        ("rate_limit", 101),
        ("max_reviews", 102),
        ("no_reviewable_files", 103),
        ("diff_too_large", 104),
        ("agent_unparseable", 105),
        ("agent_timeout", 106),
    ]
    lines: list[str] = []
    all_ok = True
    for reason, pr in reasons:
        count = await _exercise_reason(reason, pr)
        ok = count == 1
        if not ok:
            all_ok = False
        lines.append(f"{reason:<24} pr=#{pr}  comments_posted={count}  {'OK' if ok else 'FAIL'}")

    for line in lines:
        print(line)
    print("ALL OK" if all_ok else "ALL FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
