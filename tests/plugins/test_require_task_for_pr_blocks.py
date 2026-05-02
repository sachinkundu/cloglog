"""T-371 pin: ``require-task-for-pr.sh`` MUST hard-block ``gh pr create``
when no ``.cloglog/state.json`` exists for the working directory.

Pre-T-371 the hook was advisory (``exit 0`` after a ``REMINDER`` print).
Close-wave / one-off operator PRs slipped through with no board task,
producing the 7 stale ``Close worktree wt-...`` rows that prompted the
ticket. The blocker is the only way to make "every PR has a task" a
hard invariant; this test pins that contract.

The hook resolves state via:
    1. ``$CLAUDE_PROJECT_DIR/.cloglog/state.json`` if set
    2. ``$PWD/.cloglog/state.json`` walking upward to the filesystem root

When neither yields a file, the hook MUST exit non-zero (we accept any
non-zero so this test does not couple to the exit-2 convention beyond
the contract that the call is rejected).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "plugins/cloglog/hooks/require-task-for-pr.sh"


def _run_hook(
    payload: dict, *, cwd: Path, env_extra: dict | None = None
) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


def test_hook_exists_and_executable() -> None:
    assert HOOK.exists(), f"{HOOK} missing"
    assert HOOK.stat().st_mode & 0o111, f"{HOOK} must be executable"


def test_hook_blocks_gh_pr_create_without_state_json(tmp_path: Path) -> None:
    """No state.json anywhere → exit non-zero with an actionable message."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create --base main --head wt-foo"},
    }
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode != 0, (
        "require-task-for-pr.sh must reject gh pr create when no "
        "state.json is reachable from cwd. Pre-T-371 the hook printed "
        "a reminder and exit 0'd; that is exactly the regression this "
        "pin catches."
    )
    msg = result.stderr.lower()
    assert "blocked" in msg or "register_agent" in msg or "start_task" in msg, (
        "Block message must point the agent at the corrective MCP "
        "calls (register_agent / start_task). Without that the hook "
        "is silent-fail from the agent's perspective."
    )


def test_hook_passes_through_non_pr_create_bash_commands(tmp_path: Path) -> None:
    """Hook must not interfere with unrelated bash commands."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
    }
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode == 0, (
        "Hook must exit 0 for Bash commands that do not invoke "
        "`gh pr create`. The blocker scope is PR creation only."
    )


def test_hook_passes_through_non_bash_tools(tmp_path: Path) -> None:
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": "/tmp/foo", "old_string": "a", "new_string": "b"},
    }
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode == 0


def test_hook_blocks_gh_pr_create_with_malformed_state_json(tmp_path: Path) -> None:
    """state.json missing required fields → block with exit non-zero."""
    state_dir = tmp_path / ".cloglog"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("{}")  # no worktree_id / agent_token / backend_url
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create"},
    }
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode != 0
    assert "malformed" in result.stderr.lower() or "missing" in result.stderr.lower()


def test_hook_walks_up_to_find_state_json(tmp_path: Path) -> None:
    """state.json at a parent directory must be discovered from a deeper cwd."""
    state_dir = tmp_path / ".cloglog"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "worktree_id": "deadbeef",
                "agent_token": "tok",
                "backend_url": "http://127.0.0.1:1",  # unreachable on purpose
            }
        )
    )
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr create"},
    }
    result = _run_hook(payload, cwd=nested)
    # Backend is unreachable → blocked, but the failure must come from
    # the API call (proving state.json was found and parsed), not from
    # the "no state.json" branch.
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "no .cloglog/state.json" not in err, (
        "Hook must walk parent directories to find state.json. The "
        "find-state branch fired here, masking that the parent walk "
        "is broken."
    )
