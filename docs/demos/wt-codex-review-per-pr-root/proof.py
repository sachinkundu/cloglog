"""In-process proofs for T-278 ``resolve_pr_review_root``.

Run modes (one per CLI arg):
- ``happy``    — worktree row + on-disk path → returns worktree path, no fallback warning
- ``fallback`` — no worktree row → returns settings fallback AND logs reason
- ``drift``    — worktree HEAD != event SHA → returns worktree path AND logs drift

Each mode prints only boolean OK/FAIL lines so the output is verify-safe
(no live SHAs, no timestamps, no PIDs). T-278.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from src.agent.interfaces import IWorktreeQuery, WorktreeRow
from src.gateway.review_engine import resolve_pr_review_root
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType
from src.shared.config import settings

_HEAD_BRANCH = "wt-t278-demo"
_PROJECT_ID = uuid.UUID("18bb5985-8476-4f53-8172-cc452feb762d")


class _StubQuery:
    """Minimal ``IWorktreeQuery`` returning one canned row or ``None``."""

    def __init__(self, row: WorktreeRow | None) -> None:
        self._row = row

    async def find_by_branch(
        self, project_id: uuid.UUID, branch_name: str
    ) -> WorktreeRow | None:
        if self._row is None:
            return None
        if self._row.project_id != project_id or self._row.branch_name != branch_name:
            return None
        return self._row


def _event(head_sha: str = "a" * 40) -> WebhookEvent:
    return WebhookEvent(
        type=WebhookEventType.PR_OPENED,
        delivery_id="demo-t278",
        repo_full_name="sachinkundu/cloglog",
        pr_number=278,
        pr_url="https://github.com/sachinkundu/cloglog/pull/278",
        head_branch=_HEAD_BRANCH,
        base_branch="main",
        sender="sachinkundu",
        raw={"pull_request": {"head": {"sha": head_sha}}},
    )


def _init_git_repo(path: Path) -> str:
    """Init a git repo at ``path`` with one empty commit; return the HEAD SHA."""
    path.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(path),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        env=env,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout.strip()


class _LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


def _run_resolver(
    query: IWorktreeQuery, event: WebhookEvent
) -> tuple[Path, list[str]]:
    cap = _LogCapture()
    logger = logging.getLogger("src.gateway.review_engine")
    prior_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(cap)
    try:

        async def _call() -> Path:
            return await resolve_pr_review_root(
                event, project_id=_PROJECT_ID, worktree_query=query
            )

        result = asyncio.run(_call())
    finally:
        logger.removeHandler(cap)
        logger.setLevel(prior_level)
    return result, cap.messages()


def _happy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        worktree_dir = Path(tmp) / "wt-t278-demo"
        sha = _init_git_repo(worktree_dir)
        row = WorktreeRow(
            id=uuid.uuid4(),
            project_id=_PROJECT_ID,
            worktree_path=str(worktree_dir),
            branch_name=_HEAD_BRANCH,
            status="online",
        )
        result, messages = _run_resolver(_StubQuery(row), _event(head_sha=sha))
        print(f"returns_worktree_path={result == worktree_dir}")
        print(
            "no_fallback_warning="
            f"{not any('review_source=fallback' in m for m in messages)}"
        )
        print(
            "no_drift_warning="
            f"{not any('review_source_drift' in m for m in messages)}"
        )
        print(
            "logged_worktree_source="
            f"{any('review_source=worktree' in m for m in messages)}"
        )


def _fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fallback_root = Path(tmp) / "host-fallback"
        fallback_root.mkdir()
        # Override the host-level fallback for the duration of this proof.
        original = settings.review_source_root
        settings.review_source_root = fallback_root
        try:
            result, messages = _run_resolver(_StubQuery(None), _event())
        finally:
            settings.review_source_root = original
        print(f"returns_fallback_path={result == fallback_root}")
        print(
            "logged_no_matching_worktree="
            f"{any('reason=no_matching_worktree' in m for m in messages)}"
        )


def _drift() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        worktree_dir = Path(tmp) / "wt-t278-drift"
        worktree_sha = _init_git_repo(worktree_dir)
        # Build an event SHA that differs from the worktree's real SHA.
        event_sha = "b" * 40 if not worktree_sha.startswith("b") else "c" * 40
        row = WorktreeRow(
            id=uuid.uuid4(),
            project_id=_PROJECT_ID,
            worktree_path=str(worktree_dir),
            branch_name=_HEAD_BRANCH,
            status="online",
        )
        result, messages = _run_resolver(_StubQuery(row), _event(head_sha=event_sha))
        print(f"returns_worktree_path={result == worktree_dir}")
        print(f"shas_differ={worktree_sha != event_sha}")
        print(
            "logged_drift_warning="
            f"{any('review_source_drift' in m for m in messages)}"
        )


_MODES = {"happy": _happy, "fallback": _fallback, "drift": _drift}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in _MODES:
        print(f"usage: {sys.argv[0]} <{'|'.join(sorted(_MODES))}>", file=sys.stderr)
        raise SystemExit(2)
    _MODES[sys.argv[1]]()
