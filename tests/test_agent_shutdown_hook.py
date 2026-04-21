"""Regression guard: T-243.

`plugins/cloglog/hooks/agent-shutdown.sh` MUST write a structured
`agent_unregistered` event to the project-root inbox on SessionEnd, even
when the agent itself skipped the explicit emit (the hook is the
best-effort backstop). The event must carry absolute artifact paths so the
main agent's close-wave flow can read them after the worktree is torn down.

See `docs/design/agent-lifecycle.md` §2 step 5.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "plugins" / "cloglog" / "hooks" / "agent-shutdown.sh"


def _run_hook(cwd: Path, env: dict[str, str]) -> None:
    payload = json.dumps({"cwd": str(cwd)})
    # The hook's curl-to-unregister-by-path step is gated on a non-empty
    # API key; with HOME pointing at an empty dir and CLOGLOG_API_KEY unset,
    # no network call is attempted and the test stays hermetic.
    subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def stub_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Scratch main repo + attached worktree, returning (main_root, wt_path)."""
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "init",
            "-q",
        ],
        check=True,
    )
    # Normalize to `main` so the hook's `git log main..HEAD` resolves; local
    # git versions may default to `master`.
    subprocess.run(["git", "-C", str(main), "branch", "-M", "main"], check=True)
    wt = tmp_path / "wt-sim"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(wt), "-b", "wt-sim"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "T-243 hook backstop test",
            "-q",
        ],
        check=True,
    )
    (main / ".cloglog").mkdir()
    (main / ".cloglog" / "inbox").touch()
    return main, wt


def test_hook_writes_agent_unregistered_backstop(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    main, wt = stub_worktree
    # Empty HOME so ~/.cloglog/credentials is absent; PATH kept so git/bash resolve.
    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)

    inbox = (main / ".cloglog" / "inbox").read_text().strip().splitlines()
    assert inbox, "main agent inbox must receive the backstop event"
    event = json.loads(inbox[-1])

    assert event["type"] == "agent_unregistered"
    assert event["worktree"] == "wt-sim"
    assert event["reason"] == "best_effort_backstop_from_session_end_hook"
    assert event["ts"], "ts must be present (ISO-8601 from `date -Iseconds`)"

    artifacts = event["artifacts"]
    # Absolute paths — the main agent reads these after the worktree is torn
    # down and the relative root is gone by then.
    assert Path(artifacts["work_log"]).is_absolute()
    assert Path(artifacts["learnings"]).is_absolute()
    assert Path(artifacts["work_log"]).exists()
    assert Path(artifacts["learnings"]).exists()


def test_hook_derives_tasks_completed_from_git_log(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    main, wt = stub_worktree
    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)

    event = json.loads((main / ".cloglog" / "inbox").read_text().strip().splitlines()[-1])
    # The sole commit on the worktree references T-243; the hook's
    # `git log main..HEAD | jq -Rn 'scan("T-[0-9]+")'` must pick it up.
    assert event["tasks_completed"] == ["T-243"]


def test_hook_emits_empty_tasks_array_when_no_refs_in_commits(
    tmp_path: Path,
) -> None:
    """A worktree whose commits carry no T-NNN reference (e.g., a research
    branch) must still produce a well-formed event. `tasks_completed` is an
    empty JSON array, never absent and never null."""
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "init",
            "-q",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(main), "branch", "-M", "main"], check=True)
    wt = tmp_path / "wt-no-refs"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(wt), "-b", "wt-no-refs"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "chore: bump deps",
            "-q",
        ],
        check=True,
    )
    (main / ".cloglog").mkdir()
    (main / ".cloglog" / "inbox").touch()

    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)

    event = json.loads((main / ".cloglog" / "inbox").read_text().strip().splitlines()[-1])
    assert event["tasks_completed"] == []


def test_hook_is_idempotent_across_multiple_firings(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    """Close-wave may kill an agent after the agent already wrote its own
    event; the hook then fires and writes a second line. Both events must be
    valid JSON so the close-wave consumer can deduplicate on (worktree, ts)."""
    main, wt = stub_worktree
    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)
    _run_hook(wt, env)

    lines = (main / ".cloglog" / "inbox").read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        event = json.loads(line)
        assert event["type"] == "agent_unregistered"
        assert event["worktree"] == "wt-sim"
