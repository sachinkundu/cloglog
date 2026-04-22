"""Regression guard: T-220 cooperative-shutdown wait helper.

``scripts/wait_for_agent_unregistered.py`` is the scripted portion of the
``close-wave`` and ``reconcile`` skills' cooperative shutdown flow. It polls
the main agent's inbox for an ``agent_unregistered`` event from a specific
worktree and reports success or timeout so the calling skill can decide
whether to fall back to ``force_unregister``.

See ``docs/design/agent-lifecycle.md`` §2 (shutdown sequence) and §5
(three-tier shutdown).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "scripts" / "wait_for_agent_unregistered.py"


def _run_helper(
    inbox: Path, worktree: str, timeout: float, poll_interval: float = 0.05
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--worktree",
            worktree,
            "--inbox",
            str(inbox),
            "--timeout",
            str(timeout),
            "--poll-interval",
            str(poll_interval),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _unregistered_event(
    worktree: str = "wt-coop",
    worktree_id: str = "11111111-2222-3333-4444-555555555555",
    tasks_completed: list[str] | None = None,
) -> str:
    event = {
        "type": "agent_unregistered",
        "worktree": worktree,
        "worktree_id": worktree_id,
        "ts": "2026-04-22T12:00:00Z",
        "tasks_completed": tasks_completed or ["T-220"],
        "artifacts": {
            "work_log": "/tmp/wt-coop/shutdown-artifacts/work-log.md",
            "learnings": "/tmp/wt-coop/shutdown-artifacts/learnings.md",
        },
        "reason": "all_assigned_tasks_complete",
    }
    return json.dumps(event)


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    path = tmp_path / "inbox"
    path.touch()
    return path


def test_returns_zero_when_matching_event_arrives_mid_wait(inbox: Path) -> None:
    """Cooperative happy path — the agent emits ``agent_unregistered`` while
    the skill is waiting, so the helper exits 0 and the skill proceeds to
    teardown without invoking ``force_unregister``."""

    def writer() -> None:
        time.sleep(0.2)
        with inbox.open("a") as f:
            f.write(_unregistered_event() + "\n")

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()

    result = _run_helper(inbox, "wt-coop", timeout=5.0)
    thread.join(timeout=1.0)

    assert result.returncode == 0, (
        f"helper should exit 0 on matching event; stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_times_out_when_no_event_arrives(inbox: Path) -> None:
    """Cooperative-timeout path — the agent is wedged and never emits. The
    helper exits 1 so the skill can fall back to ``force_unregister`` and
    record the fallback in its work log."""
    result = _run_helper(inbox, "wt-coop", timeout=0.3)
    assert result.returncode == 1, (
        f"helper should exit 1 on timeout; stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_ignores_events_for_other_worktrees(inbox: Path) -> None:
    """Multiple worktrees share the main inbox. The helper must only match
    events for its own worktree — an ``agent_unregistered`` from a sibling
    worktree must not satisfy the wait for ``wt-coop``."""

    def writer() -> None:
        time.sleep(0.1)
        with inbox.open("a") as f:
            f.write(_unregistered_event(worktree="wt-other") + "\n")

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()

    result = _run_helper(inbox, "wt-coop", timeout=0.5)
    thread.join(timeout=1.0)

    assert result.returncode == 1


def test_ignores_events_already_in_inbox_before_helper_started(inbox: Path) -> None:
    """The helper records the inbox size at entry and only reads events
    appended after that point. Stale ``agent_unregistered`` lines from a
    previous session must not satisfy a fresh cooperative-shutdown wait."""
    inbox.write_text(_unregistered_event() + "\n")

    result = _run_helper(inbox, "wt-coop", timeout=0.3)
    assert result.returncode == 1, "stale pre-existing event must not satisfy the wait"


def test_ignores_malformed_json_lines(inbox: Path) -> None:
    """A corrupted inbox line (partial write, truncation) must not crash the
    helper. It continues polling and still succeeds when the real event
    arrives."""

    def writer() -> None:
        time.sleep(0.1)
        with inbox.open("a") as f:
            f.write("not json at all\n")
            f.write('{"type":"agent_unregistered"' + "\n")  # truncated
            f.write(_unregistered_event() + "\n")

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()

    result = _run_helper(inbox, "wt-coop", timeout=2.0)
    thread.join(timeout=1.0)

    assert result.returncode == 0


def test_missing_inbox_exits_two(tmp_path: Path) -> None:
    """Exit code 2 is reserved for configuration errors — the helper must
    distinguish a missing inbox from a timeout so the skill can surface the
    operator-visible failure rather than silently falling back to force."""
    missing = tmp_path / "does-not-exist"
    result = _run_helper(missing, "wt-coop", timeout=0.1)
    assert result.returncode == 2
