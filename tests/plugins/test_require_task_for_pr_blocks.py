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


def test_state_json_is_gitignored() -> None:
    """T-371 codex review HIGH: ``.cloglog/state.json`` carries an
    ``agent_token`` and MUST never be tracked. The supervisor's main
    session calls ``register_agent`` from the repo root, so the file
    lands in the main checkout — without an explicit ignore, the
    operator's first ``git status`` after ``/cloglog setup`` shows it
    as untracked and a careless ``git add .`` leaks the live token.
    """
    gitignore = REPO_ROOT / ".gitignore"
    body = gitignore.read_text(encoding="utf-8")
    assert ".cloglog/state.json" in body, (
        ".gitignore must list `.cloglog/state.json`. T-371 / codex "
        "review on PR #287 caught the original draft for shipping the "
        "ignore alongside the file write that introduced it."
    )
    # git check-ignore is the authoritative way to confirm the rule
    # actually matches the path under the repo root.
    rc = subprocess.run(
        ["git", "check-ignore", "-q", ".cloglog/state.json"],
        cwd=REPO_ROOT,
    ).returncode
    assert rc == 0, (
        "`git check-ignore -q .cloglog/state.json` must succeed (exit 0). "
        "Exit 1 means the path is NOT being ignored — a future edit "
        "to .gitignore that re-orders rules or adds a negation could "
        "silently regress this without tripping the substring assertion."
    )


def test_agent_shutdown_hook_clears_state_json() -> None:
    """T-371 codex review CRITICAL: SessionEnd shutdown via
    ``agent-shutdown.sh`` calls ``unregister-by-path`` directly,
    bypassing the MCP ``unregister_agent`` tool's
    ``clearWorktreeState`` call. Without an explicit rm in this
    hook, ``state.json`` survives shutdown and the next
    ``gh pr create`` in the same checkout uses a dead
    ``worktree_id`` / ``agent_token`` — the hook then routes through
    its generic "unexpected response" branch instead of the intended
    "not registered, call register_agent" branch.
    """
    hook = REPO_ROOT / "plugins/cloglog/hooks/agent-shutdown.sh"
    body = hook.read_text(encoding="utf-8")
    assert "rm -f " in body and ".cloglog/state.json" in body, (
        "agent-shutdown.sh must remove `<worktree_root>/.cloglog/"
        "state.json` after the unregister-by-path call so the hook's "
        "presence-of-state-file invariant matches the backend's "
        "actual registration state. T-371 / codex review on PR #287."
    )
    # T-371 codex round 4: the rm and the unregister-by-path payload
    # must both target the worktree ROOT, not the SessionEnd-reported
    # `$CWD` (which can be a nested subdir like `<worktree>/src`).
    assert "WORKTREE_ROOT" in body, (
        "agent-shutdown.sh must resolve the worktree root via "
        "`git rev-parse --show-toplevel` before the cleanup — "
        "Bash's reported `cwd` is not pinned to the worktree root, "
        "so a subdirectory-cwd shutdown would `rm` the wrong path "
        "and leave the canonical state.json behind."
    )
    assert 'rm -f "${WORKTREE_ROOT}/.cloglog/state.json"' in body, (
        "agent-shutdown.sh's state.json rm must use $WORKTREE_ROOT, "
        "not $CWD. Codex review on PR #287 round 4 caught the "
        "earlier $CWD-based draft that left stale tokens behind on "
        "subdirectory-cwd shutdowns."
    )
    # T-371 codex round 5: the main-repo branch of agent-shutdown.sh
    # (GIT_DIR == GIT_COMMON) must also rm state.json. The supervisor
    # writes <repo_root>/.cloglog/state.json on every /cloglog setup,
    # and without symmetric cleanup the blocker hook treats a stale
    # registration as live across main-session restarts.
    assert 'rm -f "${MAIN_ROOT}/.cloglog/state.json"' in body, (
        "agent-shutdown.sh's main-repo branch (GIT_DIR == GIT_COMMON) "
        "must rm <repo_root>/.cloglog/state.json before exiting, "
        "mirroring the worktree-branch cleanup. Without it, ending a "
        "main-agent session leaves a stale state.json behind that "
        "the blocker hook will use to authorize gh pr create on the "
        "next session start, defeating the not-registered guidance."
    )
    assert "MAIN_ROOT=" in body, (
        "agent-shutdown.sh must resolve MAIN_ROOT via "
        "`git rev-parse --show-toplevel` in the main-repo branch — "
        "$CWD can be a nested subdir, same hazard the worktree "
        "branch was fixed for in round 4."
    )


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
