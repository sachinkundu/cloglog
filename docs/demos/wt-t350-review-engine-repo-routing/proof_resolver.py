"""T-350 proof: resolve_pr_review_root() is repo-aware.

Drives ``resolve_pr_review_root`` directly with two synthetic webhook
events to demonstrate the two acceptance branches:

  (i) ``sachinkundu/antisocial`` close-wave PR (no worktree row, no
      registry entry) → resolver returns ``None`` (REFUSED). The
      engine would post a one-shot ``unconfigured_repo`` skip comment
      instead of routing the review to cloglog's source. This is the
      original antisocial PR #2 incident shape.

  (ii) ``sachinkundu/cloglog`` close-wave PR (no worktree row, but
       registry entry exists for cloglog) → resolver returns the
       registry path, so cloglog's review pipeline keeps working.

A plain ``import`` of this module does NOT trigger pytest's session
fixtures (``conftest.py`` is bypassed when pytest itself is not the
loader), so this proof runs deterministically inside ``showboat
verify`` with no Postgres dependency.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from src.gateway.review_engine import resolve_pr_review_root
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType


class _NoMatchQuery:
    """Stub IWorktreeQuery that mirrors the antisocial PR #2 / cloglog
    close-wave PR shape: no worktree on this host owns the close-off
    branch, no task pr_url binding hits.
    """

    async def find_by_branch(self, project_id, branch_name):  # noqa: ARG002
        return None

    async def find_by_pr_url(self, project_id, pr_url):  # noqa: ARG002
        return None


def _make_event(repo_full_name: str, branch: str) -> WebhookEvent:
    return WebhookEvent(
        type=WebhookEventType.PR_OPENED,
        delivery_id=f"d-{repo_full_name}-{branch}",
        repo_full_name=repo_full_name,
        pr_number=2,
        pr_url=f"https://github.com/{repo_full_name}/pull/2",
        head_branch=branch,
        base_branch="main",
        sender="sachinkundu",
        raw={
            "pull_request": {"head": {"sha": ""}},
            "repository": {"full_name": repo_full_name},
        },
    )


def _init_git_repo(path: Path) -> None:
    """Make ``path`` a real git repo so the resolver's
    ``--git-common-dir`` validation accepts it (T-350 round 5
    tightened Path 2 to require git, not just a directory)."""
    import os
    import subprocess

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


async def _drive() -> tuple[object, object]:
    with tempfile.TemporaryDirectory() as tmp:
        cloglog_root = Path(tmp) / "cloglog-prod"
        _init_git_repo(cloglog_root)
        registry = {"sachinkundu/cloglog": cloglog_root}

        # Force the legacy fallback to ALSO point at cloglog-prod, so a
        # regression that ignored the registry would visibly route the
        # antisocial PR there — the proof would then show the wrong
        # answer instead of vacuously passing.
        with (
            patch(
                "src.gateway.review_engine.settings.review_repo_roots",
                registry,
            ),
            patch(
                "src.gateway.review_engine.settings.review_source_root",
                cloglog_root,
            ),
        ):
            antisocial_event = _make_event("sachinkundu/antisocial", "wt-close-2026-04-29-wave-1")
            cloglog_event = _make_event("sachinkundu/cloglog", "wt-close-2026-04-29-wave-7")
            antisocial_result = await resolve_pr_review_root(
                antisocial_event,
                project_id=uuid.uuid4(),
                worktree_query=_NoMatchQuery(),
            )
            cloglog_result = await resolve_pr_review_root(
                cloglog_event,
                project_id=uuid.uuid4(),
                worktree_query=_NoMatchQuery(),
            )
            cloglog_path = (
                cloglog_result.path.relative_to(tmp) if cloglog_result is not None else None
            )
            return antisocial_result, cloglog_path


def main() -> None:
    antisocial, cloglog_relpath = asyncio.run(_drive())
    print("(i)  antisocial close-wave (unconfigured repo):")
    print(f"     resolver returned: {antisocial!r}")
    assert antisocial is None, "T-350 regression: antisocial PR fell back to cloglog source"
    print("     OK — REFUSED (engine posts unconfigured_repo skip)")
    print()
    print("(ii) cloglog close-wave (registry hit):")
    print(f"     resolver returned path: {cloglog_relpath}")
    assert str(cloglog_relpath) == "cloglog-prod", (
        "T-350 regression: cloglog close-wave PR did not route via registry"
    )
    print("     OK — routed to cloglog's review root via registry")


if __name__ == "__main__":
    main()
