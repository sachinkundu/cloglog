"""In-process proof that a SHA mismatch routes through _create_review_checkout
and returns PrReviewRoot(is_temp=True). T-281.

We patch _create_review_checkout to return a fake temp path — exercises
the SHA-check branch without running real git subprocesses. Exits 0 on
pass, non-zero on fail.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[3]


sys.path.insert(0, str(_repo_root()))

import src.gateway.review_engine as re_module  # noqa: E402
from src.agent.interfaces import WorktreeRow  # noqa: E402
from src.gateway.review_engine import resolve_pr_review_root  # noqa: E402
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType  # noqa: E402


class _StubQuery:
    def __init__(self, row: WorktreeRow | None) -> None:
        self._row = row

    async def find_by_branch(self, project_id, branch_name):  # type: ignore[no-untyped-def]
        if self._row is None:
            return None
        if self._row.project_id != project_id:
            return None
        if self._row.branch_name != branch_name:
            return None
        return self._row

    async def find_by_pr_url(self, project_id, pr_url):  # type: ignore[no-untyped-def]
        return None


def _init_git_repo_at(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
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
    r = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return r.stdout.strip()


async def _main() -> None:
    project_id = uuid.uuid4()
    with tempfile.TemporaryDirectory() as tmp:
        worktree_dir = Path(tmp) / "wt-stale"
        worktree_sha = _init_git_repo_at(worktree_dir)
        event_sha = "b" * 40 if not worktree_sha.startswith("b") else "c" * 40
        assert worktree_sha != event_sha

        fake_temp = Path(tmp) / "fake-temp-checkout"
        fake_temp.mkdir()

        create_called_with: dict[str, object] = {}

        async def _fake_create_review_checkout(
            main_clone, *, head_sha, pr_number, head_branch=None
        ):  # type: ignore[no-untyped-def]
            create_called_with["head_sha"] = head_sha
            create_called_with["pr_number"] = pr_number
            create_called_with["head_branch"] = head_branch
            return fake_temp

        orig = re_module._create_review_checkout
        re_module._create_review_checkout = _fake_create_review_checkout
        try:
            row = WorktreeRow(
                id=uuid.uuid4(),
                project_id=project_id,
                worktree_path=str(worktree_dir),
                branch_name="wt-stale",
                status="online",
            )
            event = WebhookEvent(
                type=WebhookEventType.PR_OPENED,
                delivery_id="d-281-sha",
                repo_full_name="sachinkundu/cloglog",
                pr_number=281,
                pr_url="https://github.com/sachinkundu/cloglog/pull/281",
                head_branch="wt-stale",
                base_branch="main",
                sender="sachinkundu",
                raw={"pull_request": {"head": {"sha": event_sha}}},
            )
            result = await resolve_pr_review_root(
                event, project_id=project_id, worktree_query=_StubQuery(row)
            )
        finally:
            re_module._create_review_checkout = orig

        assert result.path == fake_temp, (
            f"SHA mismatch must route to temp checkout; got {result.path}"
        )
        assert result.is_temp is True
        assert result.main_clone is not None, "Temp-dir result must carry cleanup anchor"
        assert create_called_with["head_sha"] == event_sha, (
            f"Temp checkout must be materialized at event.head_sha; "
            f"got {create_called_with['head_sha']!r}"
        )
        assert create_called_with["pr_number"] == 281
        assert create_called_with["head_branch"] == "wt-stale"

        print("sha_mismatch_triggers_temp_dir=yes")
        print("is_temp=yes")
        print("create_called_with_event_head_sha=yes")
        print("cleanup_anchor_set=yes")


if __name__ == "__main__":
    asyncio.run(_main())
