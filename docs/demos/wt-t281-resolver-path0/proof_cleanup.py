"""In-process proof that _review_pr cleans up a temp-dir review checkout
even when the review stage raises. T-281.

We stub resolve_pr_review_root to return an is_temp=True root, stub the
ReviewLoop to raise, and assert _remove_review_checkout is awaited in
the finally block. Exits 0 on pass, non-zero on fail.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[3]


sys.path.insert(0, str(_repo_root()))

import src.gateway.review_engine as re_module  # noqa: E402
import src.gateway.review_loop as loop_module  # noqa: E402
from src.gateway.review_engine import PrReviewRoot, ReviewEngineConsumer  # noqa: E402
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType  # noqa: E402


class _FailingLoop:
    def __init__(self, reviewer, **kwargs):  # type: ignore[no-untyped-def]
        self._stage = str(kwargs.get("stage", "?"))

    async def run(self, *, diff):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated reviewer crash")


class _RegistryCtx:
    async def __aenter__(self):  # type: ignore[no-untyped-def]
        class _NoopRegistry:
            pass

        return _NoopRegistry()

    async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
        return False


class _WorktreeQueryCtx:
    async def __aenter__(self):  # type: ignore[no-untyped-def]
        class _NoopQuery:
            async def find_by_branch(self, project_id, branch_name):  # type: ignore[no-untyped-def]
                return None

            async def find_by_pr_url(self, project_id, pr_url):  # type: ignore[no-untyped-def]
                return None

        return _NoopQuery()

    async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
        return False


async def _main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        fake_temp = tmp_path / "temp-checkout"
        fake_temp.mkdir()
        main_clone = tmp_path / "main-clone"
        main_clone.mkdir()

        temp_root = PrReviewRoot(path=fake_temp, is_temp=True, main_clone=main_clone)
        remove_calls: list[tuple[Path, Path]] = []

        async def _fake_remove(main, path):  # type: ignore[no-untyped-def]
            remove_calls.append((main, path))

        async def _fake_resolve(*args, **kwargs):  # type: ignore[no-untyped-def]
            return temp_root

        async def _fake_gh_token():  # type: ignore[no-untyped-def]
            return "fake-token"

        async def _fake_count_bot_reviews(*args, **kwargs):  # type: ignore[no-untyped-def]
            return 0

        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-281-cleanup",
            repo_full_name="sachinkundu/cloglog",
            pr_number=281,
            pr_url="https://github.com/sachinkundu/cloglog/pull/281",
            head_branch="wt-t281-temp",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": "e" * 40}}},
        )

        # Save originals for restore
        saves = {
            "resolve": re_module.resolve_pr_review_root,
            "remove": re_module._remove_review_checkout,
            "count": re_module.count_bot_reviews,
            "loop": loop_module.ReviewLoop,
        }

        # Stub everything that would otherwise hit the network / DB
        re_module.resolve_pr_review_root = _fake_resolve
        re_module._remove_review_checkout = _fake_remove
        re_module.count_bot_reviews = _fake_count_bot_reviews
        loop_module.ReviewLoop = _FailingLoop

        # Stub token fetchers (imported lazily in _review_pr)
        import src.gateway.github_token as gt_module

        token_saves = {
            "gh_app": gt_module.get_github_app_token,
            "codex": gt_module.get_codex_reviewer_token,
        }
        gt_module.get_github_app_token = _fake_gh_token
        gt_module.get_codex_reviewer_token = _fake_gh_token

        class _FakeSession:
            pass

        def _fake_session_factory():  # type: ignore[no-untyped-def]
            return _FakeSession()

        consumer = ReviewEngineConsumer(
            codex_available=True,
            opencode_available=False,
            session_factory=_fake_session_factory,
        )

        # Bypass the real diff fetch + project lookup
        async def _fake_fetch_diff(*args, **kwargs):  # type: ignore[no-untyped-def]
            return "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"

        async def _fake_resolve_project(*args, **kwargs):  # type: ignore[no-untyped-def]
            return uuid.uuid4()

        consumer._fetch_pr_diff = _fake_fetch_diff  # type: ignore[method-assign]
        consumer._resolve_project_id = _fake_resolve_project  # type: ignore[method-assign]
        consumer._registry = lambda: _RegistryCtx()  # type: ignore[method-assign]
        consumer._worktree_query = lambda: _WorktreeQueryCtx()  # type: ignore[method-assign]

        crashed = False
        try:
            await consumer._review_pr(event)
        except RuntimeError as err:
            assert "simulated reviewer crash" in str(err)
            crashed = True
        finally:
            re_module.resolve_pr_review_root = saves["resolve"]
            re_module._remove_review_checkout = saves["remove"]
            re_module.count_bot_reviews = saves["count"]
            loop_module.ReviewLoop = saves["loop"]
            gt_module.get_github_app_token = token_saves["gh_app"]
            gt_module.get_codex_reviewer_token = token_saves["codex"]

        assert crashed, "Test wiring broken — reviewer stub did not raise"
        assert len(remove_calls) == 1, (
            f"Expected 1 cleanup call, got {len(remove_calls)}"
        )
        call_main, call_path = remove_calls[0]
        assert call_main == main_clone, (
            f"Cleanup must target main_clone={main_clone}, got {call_main}"
        )
        assert call_path == fake_temp, (
            f"Cleanup must target fake_temp={fake_temp}, got {call_path}"
        )

        print("reviewer_raised=yes")
        print("remove_called_once=yes")
        print("remove_called_with_main_clone=yes")
        print("remove_called_with_temp_path=yes")


if __name__ == "__main__":
    asyncio.run(_main())
