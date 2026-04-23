"""T-275 verify-safe proof: settings.opencode_enabled=False skips stage A.

Runs the real ``ReviewEngineConsumer._review_pr`` with a stubbed ``ReviewLoop``
so we can observe which stages execute without touching the network, the DB,
or a subprocess. Every patched path is deterministic; the process exits 0 iff
stage A was skipped AND stage B ran.

Verify-safe — no pytest, no ollama, no GitHub, no conftest fixtures. Safe to
run from ``uvx showboat exec`` on every ``make quality``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.gateway.review_engine import ReviewEngineConsumer
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType

SAMPLE_DIFF = (
    "diff --git a/src/x.py b/src/x.py\n"
    "--- a/src/x.py\n"
    "+++ b/src/x.py\n"
    "@@ -1 +1 @@\n"
    "-a\n"
    "+b\n"
)


class _NoopRegistryCtx:
    async def __aenter__(self) -> object:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _event() -> WebhookEvent:
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


async def _run(opencode_enabled: bool) -> tuple[int, int]:
    stage_runs: dict[str, int] = {"opencode": 0, "codex": 0}

    class _StubLoop:
        def __init__(self, _reviewer: object, **kwargs: object) -> None:
            self._stage = str(kwargs.get("stage", "?"))

        async def run(self, *, diff: str) -> object:
            stage_runs[self._stage] = stage_runs.get(self._stage, 0) + 1
            return type("Outcome", (), {"turns_used": 1, "errors": []})()

    consumer = ReviewEngineConsumer(
        codex_available=True,
        opencode_available=True,
        session_factory=MagicMock(),
    )

    with (
        patch("src.gateway.review_engine.settings.opencode_enabled", opencode_enabled),
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
        patch.object(consumer, "_fetch_pr_diff", new=AsyncMock(return_value=SAMPLE_DIFF)),
        patch.object(
            consumer,
            "_resolve_project_id",
            new=AsyncMock(return_value=uuid4()),
        ),
        patch.object(consumer, "_registry", new=lambda: _NoopRegistryCtx()),
    ):
        await consumer._review_pr(_event())

    return stage_runs["opencode"], stage_runs["codex"]


async def _main() -> None:
    a_off, b_off = await _run(opencode_enabled=False)
    print(f"stage_a_runs_when_disabled={a_off}")
    print(f"stage_b_runs_when_disabled={b_off}")
    a_on, b_on = await _run(opencode_enabled=True)
    print(f"stage_a_runs_when_enabled={a_on}")
    print(f"stage_b_runs_when_enabled={b_on}")
    assert a_off == 0, f"stage A must be skipped when disabled, got {a_off}"
    assert b_off == 1, f"stage B must still run when opencode disabled, got {b_off}"
    assert a_on == 1, f"stage A must run when enabled, got {a_on}"
    assert b_on == 1, f"stage B must run when opencode enabled, got {b_on}"
    print("sequencer_proof=PASS")


if __name__ == "__main__":
    asyncio.run(_main())
