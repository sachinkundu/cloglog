"""In-process proof that resolve_pr_review_root returns the main-agent
worktree via Path 0 (tasks.pr_url → task.worktree_id join) for a
close-out PR whose head_branch has no worktree row. T-281.

Run with ``python3 proof_path0.py`` — no pytest, no DB. Exits 0 on pass,
non-zero on fail. The PATHS and printed booleans are the demo evidence.
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

from src.agent.interfaces import WorktreeRow  # noqa: E402
from src.gateway.review_engine import PrReviewRoot, resolve_pr_review_root  # noqa: E402
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType  # noqa: E402


class _StubQuery:
    """In-memory stub: Path 0 hits, Path 1 misses — the close-out shape."""

    def __init__(self, project_id: uuid.UUID, main_clone: Path) -> None:
        self._pr_url_row = WorktreeRow(
            id=uuid.uuid4(),
            project_id=project_id,
            worktree_path=str(main_clone),
            branch_name="main",
            status="online",
        )

    async def find_by_branch(self, project_id, branch_name):  # type: ignore[no-untyped-def]
        # Main agent has no worktree for the close-out branch.
        return None

    async def find_by_pr_url(self, project_id, pr_url):  # type: ignore[no-untyped-def]
        if not pr_url or self._pr_url_row.project_id != project_id:
            return None
        return self._pr_url_row


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
        main_clone = Path(tmp) / "main-clone"
        sha = _init_git_repo_at(main_clone)

        event = WebhookEvent(
            type=WebhookEventType.PR_OPENED,
            delivery_id="d-281",
            repo_full_name="sachinkundu/cloglog",
            pr_number=281,
            pr_url="https://github.com/sachinkundu/cloglog/pull/281",
            head_branch="wt-close-2026-04-24-foo",
            base_branch="main",
            sender="sachinkundu",
            raw={"pull_request": {"head": {"sha": sha}}},
        )

        result = await resolve_pr_review_root(
            event, project_id=project_id, worktree_query=_StubQuery(project_id, main_clone)
        )

        assert isinstance(result, PrReviewRoot), f"Expected PrReviewRoot, got {type(result)}"
        assert result.path == main_clone, (
            f"Path 0 must win even when head_branch has no worktree row. "
            f"Expected {main_clone}, got {result.path}"
        )
        assert result.is_temp is False, "SHA matches → no temp checkout"
        assert result.main_clone is None, "is_temp=False must leave main_clone unset"
        print("path_0_hits_for_close_out_pr=yes")
        print("is_temp=no")
        print("path_matches_main_clone=yes")


if __name__ == "__main__":
    asyncio.run(_main())
