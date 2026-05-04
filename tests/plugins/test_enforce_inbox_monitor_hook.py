"""T-370 pin: ``enforce-inbox-monitor-after-pr.sh`` MUST block the next
agent action when a PR is created without an active inbox Monitor.

The github-bot SKILL mandates arming a Monitor on <worktree>/.cloglog/inbox
immediately after ``gh pr create``. Previously the rule was prose-only
(``remind-pr-update.sh`` prints a reminder and exits 0). This hook makes it
a hard block so the 2026-05-02 PR #285 incident (main agent missed a codex
MEDIUM finding for 30 min after skipping the monitor-arm) cannot recur.

The hook is a PostToolUse hook that:
1. Fires on Bash commands containing ``gh pr create``; ignores all others.
2. Resolves the inbox path via ``git rev-parse --git-common-dir`` to
   distinguish the main project checkout from a worktree.
3. Checks ``ps -ww -eo args`` for a running ``tail`` process on that path.
4. Blocks (exit 2) with a Monitor prescription if no monitor is found.
5. Exits 0 silently when a monitor IS running on the resolved path.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "plugins/cloglog/hooks/enforce-inbox-monitor-after-pr.sh"


# ── helpers ──────────────────────────────────────────────────────────────


FAKE_PR_URL = "https://github.com/owner/repo/pull/42"


def _make_payload(
    command: str,
    cwd: str | Path = "/tmp",
    tool_name: str = "Bash",
    tool_response: str | None = None,
) -> dict:
    """Build a hook input payload.

    Pass ``tool_response=FAKE_PR_URL`` (or any string containing a GitHub PR URL)
    for tests that need the hook to advance past the 'was a PR actually created?'
    guard and reach the monitor-presence check.
    """
    payload: dict = {
        "tool_name": tool_name,
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    if tool_response is not None:
        payload["tool_response"] = tool_response
    return payload


def _run_hook(
    payload: dict,
    *,
    cwd: Path,
    env_extra: dict | None = None,
) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
    }
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


def _make_fake_ps(output: str, tmp_path: Path) -> Path:
    """Write a fake `ps` script that echoes controlled output, add to PATH."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    ps_script = bin_dir / "ps"
    ps_script.write_text(
        textwrap.dedent(f"""\
        #!/bin/bash
        printf '%s\\n' {repr(output)}
        """)
    )
    ps_script.chmod(0o755)
    # Also copy git so hook can resolve worktree paths
    import shutil

    git_path = shutil.which("git")
    if git_path:
        (bin_dir / "git").symlink_to(git_path)
    return bin_dir


# ── existence / permissions ───────────────────────────────────────────────


def test_hook_exists_and_is_executable() -> None:
    assert HOOK.exists(), f"{HOOK} missing"
    assert HOOK.stat().st_mode & 0o111, f"{HOOK} must be executable"


def test_hook_registered_in_plugin_settings() -> None:
    settings_path = REPO_ROOT / "plugins/cloglog/settings.json"
    body = settings_path.read_text(encoding="utf-8")
    assert "enforce-inbox-monitor-after-pr.sh" in body, (
        "plugins/cloglog/settings.json must register the hook. "
        "Expected to find 'enforce-inbox-monitor-after-pr.sh' in the file."
    )


# ── command-matching ─────────────────────────────────────────────────────


def test_hook_passes_through_non_bash_tools(tmp_path: Path) -> None:
    """Non-Bash tools must be ignored unconditionally."""
    payload = _make_payload("gh pr create --base main", cwd=tmp_path, tool_name="Edit")
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode == 0


def test_hook_passes_through_unrelated_gh_commands(tmp_path: Path) -> None:
    """gh pr view, gh pr list, etc. must not trigger the check."""
    for cmd in ("gh pr view 42", "gh pr list --state open", "gh pr merge 99"):
        payload = _make_payload(cmd, cwd=tmp_path)
        result = _run_hook(payload, cwd=tmp_path)
        assert result.returncode == 0, (
            f"Hook should not fire for: {cmd!r}. "
            "Only 'gh pr create' should trigger the inbox-monitor check."
        )


def test_hook_fires_on_gh_pr_create(tmp_path: Path) -> None:
    """gh pr create with a real PR URL in tool_response → triggers check."""
    # Use a non-git tmp_path so git fails → hook exits 2 with warning
    payload = _make_payload("gh pr create --base main --head my-branch", cwd=tmp_path)
    # Simulate a successful pr create: tool_response contains a PR URL
    payload["tool_response"] = "https://github.com/owner/repo/pull/42\n"
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode == 2, (
        "Hook must exit 2 (block) when gh pr create produced a real PR URL "
        "and no inbox monitor can be confirmed. Got exit code "
        f"{result.returncode}."
    )


def test_hook_passes_when_pr_create_failed(tmp_path: Path) -> None:
    """gh pr create failure (no PR URL in tool_response) → exit 0, no block.

    Failed attempts (auth error, --dry-run, GitHub validation error) produce
    no PR and require no inbox monitor. Blocking the next action would trap
    the agent before it can fix the command and retry.
    """
    payload = _make_payload("gh pr create --base main --head my-branch", cwd=tmp_path)
    # tool_response has no GitHub PR URL — simulates a failed / dry-run call
    payload["tool_response"] = "error: pull request create failed: GraphQL: ... (422)"
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode == 0, (
        "Hook must exit 0 when tool_response contains no GitHub PR URL. "
        "A failed or --dry-run gh pr create created no PR and needs no monitor. "
        f"Got exit code {result.returncode}. stderr: {result.stderr!r}"
    )


def test_hook_passes_when_pr_create_dry_run(tmp_path: Path) -> None:
    """gh pr create --dry-run → exit 0, no block."""
    payload = _make_payload("gh pr create --dry-run --base main", cwd=tmp_path)
    payload["tool_response"] = "Would have created pull request: ..."
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode == 0, (
        "Hook must exit 0 for --dry-run output (no real PR URL). "
        f"Got exit code {result.returncode}. stderr: {result.stderr!r}"
    )


def test_hook_passes_when_tool_response_absent(tmp_path: Path) -> None:
    """No tool_response field at all → exit 0 (treat as no PR created)."""
    payload = _make_payload("gh pr create --base main", cwd=tmp_path)
    # tool_response absent — happens when hook is misconfigured as PreToolUse
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode == 0, (
        "Hook must exit 0 when tool_response is absent (no PR created). "
        f"Got exit code {result.returncode}. stderr: {result.stderr!r}"
    )


# ── block on missing monitor ─────────────────────────────────────────────


def test_hook_blocks_with_actionable_message_when_no_monitor(tmp_path: Path) -> None:
    """Blocked message must name the Monitor shape so the agent knows what to call."""
    # tmp_path is not a git repo → hook warns and exits 2
    # tool_response contains a real PR URL so the hook advances past the
    # 'was a PR created?' guard and reaches the monitor-presence check.
    payload = _make_payload("gh pr create", cwd=tmp_path, tool_response=FAKE_PR_URL)
    result = _run_hook(payload, cwd=tmp_path)
    assert result.returncode != 0
    # Message must mention Monitor so agent knows the corrective action
    assert "Monitor" in result.stderr or "tail" in result.stderr, (
        "Block message must name the expected Monitor shape "
        "(mention 'Monitor' or 'tail'). Without that the agent cannot "
        "self-correct."
    )


def test_hook_blocks_when_ps_shows_no_matching_monitor(tmp_path: Path) -> None:
    """Even inside a git repo, if ps shows no tail process → exit 2."""
    # Create a real git repo so git commands succeed
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    # Fake ps returns output without any tail process on the cloglog inbox
    bin_dir = _make_fake_ps("bash some-other-process\nnode server.js", tmp_path)
    payload = _make_payload("gh pr create --base main", cwd=tmp_path, tool_response=FAKE_PR_URL)
    result = _run_hook(
        payload,
        cwd=tmp_path,
        env_extra={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert result.returncode == 2, (
        "Hook must block (exit 2) when ps reports no tail process "
        f"matching the inbox path. stderr: {result.stderr!r}"
    )
    assert "Monitor" in result.stderr or "tail" in result.stderr, (
        "Block message must name the Monitor shape."
    )


# ── pass when monitor is running ─────────────────────────────────────────


def test_hook_passes_when_monitor_is_running_on_correct_path(tmp_path: Path) -> None:
    """If ps shows a tail process on the resolved inbox path → exit 0 silently."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    # The inbox for a main-repo cwd (not a worktree) resolves to:
    # <show-toplevel>/.cloglog/inbox  (since show-toplevel == project root)
    inbox_path = str(tmp_path / ".cloglog" / "inbox")
    fake_ps_output = f"tail -n 0 -F {inbox_path}\nbash other-process"
    bin_dir = _make_fake_ps(fake_ps_output, tmp_path)

    payload = _make_payload("gh pr create --base main", cwd=tmp_path, tool_response=FAKE_PR_URL)
    result = _run_hook(
        payload,
        cwd=tmp_path,
        env_extra={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert result.returncode == 0, (
        "Hook must exit 0 silently when a tail monitor is running on the "
        f"resolved inbox path. stderr: {result.stderr!r}"
    )
    assert result.stderr == "", "Hook must be silent (no stderr output) when monitor is confirmed."


def test_hook_passes_when_monitor_uses_legacy_relative_path(tmp_path: Path) -> None:
    """Legacy tail -f .cloglog/inbox (relative path) must be accepted.

    The setup/github-bot SKILLs document this relative form as valid for dedupe
    and crash-recovery flows. A session that still has this historical monitor
    alive must not be hard-blocked on the next ``gh pr create``.
    """
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    # Legacy monitor: relative-path form as launched by older setup/crash-recovery flows
    fake_ps_output = "tail -n 0 -F .cloglog/inbox\nbash other-process"
    bin_dir = _make_fake_ps(fake_ps_output, tmp_path)

    payload = _make_payload("gh pr create --base main", cwd=tmp_path, tool_response=FAKE_PR_URL)
    result = _run_hook(
        payload,
        cwd=tmp_path,
        env_extra={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert result.returncode == 0, (
        "Hook must accept the legacy relative-path monitor form "
        "(tail -n 0 -F .cloglog/inbox). "
        "Documented in setup/github-bot SKILLs as valid for dedupe/crash-recovery. "
        f"stderr: {result.stderr!r}"
    )


# ── worktree-vs-project-root inbox path resolution ───────────────────────


def test_hook_resolves_worktree_inbox_path_via_git_common_dir(tmp_path: Path) -> None:
    """In a worktree, inbox path is <worktree_root>/.cloglog/inbox, not the
    main project root. The hook must use --git-common-dir to distinguish them.
    """
    # Create a bare-ish main repo in a subdirectory
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    subprocess.run(["git", "init", str(main_repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(main_repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    # Create a worktree
    wt_path = tmp_path / "wt-feature"
    subprocess.run(
        ["git", "-C", str(main_repo), "worktree", "add", str(wt_path), "-b", "wt-feature"],
        check=True,
        capture_output=True,
    )

    # Hook should look for monitor on the WORKTREE inbox, not the main inbox
    wt_inbox = str(wt_path / ".cloglog" / "inbox")
    main_inbox = str(main_repo / ".cloglog" / "inbox")

    # Fake ps that has a monitor on the WORKTREE inbox
    fake_ps_wt = f"tail -n 0 -F {wt_inbox}\nbash other"
    bin_dir_wt = _make_fake_ps(fake_ps_wt, tmp_path / "bin_wt")
    (tmp_path / "bin_wt").mkdir(exist_ok=True)

    payload = _make_payload("gh pr create --base main", cwd=wt_path, tool_response=FAKE_PR_URL)
    result_wt = _run_hook(
        payload,
        cwd=wt_path,
        env_extra={"PATH": f"{bin_dir_wt}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert result_wt.returncode == 0, (
        f"Hook must pass when monitor is on the WORKTREE inbox path. stderr: {result_wt.stderr!r}"
    )

    # Fake ps that has a monitor on the MAIN inbox (wrong for a worktree)
    fake_ps_main = f"tail -n 0 -F {main_inbox}\nbash other"
    bin_dir_main = _make_fake_ps(fake_ps_main, tmp_path / "bin_main")
    (tmp_path / "bin_main").mkdir(exist_ok=True)

    result_main = _run_hook(
        payload,
        cwd=wt_path,
        env_extra={"PATH": f"{bin_dir_main}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert result_main.returncode == 2, (
        "Hook must block when only the MAIN-repo inbox has a monitor but "
        "we are inside a worktree. The worktree inbox path must be used. "
        f"stderr: {result_main.stderr!r}"
    )


# ── hook source inspection ────────────────────────────────────────────────


def test_hook_uses_git_common_dir_for_path_resolution() -> None:
    """Static pin: the hook must use --git-common-dir (not just --show-toplevel)
    to distinguish worktrees from the main checkout."""
    body = HOOK.read_text(encoding="utf-8")
    assert "--git-common-dir" in body, (
        "enforce-inbox-monitor-after-pr.sh must use "
        "`git rev-parse --git-common-dir` to resolve whether the current "
        "directory is a worktree or the main project root. Without it, "
        "the hook will look at the wrong inbox path when run from a worktree."
    )


def test_hook_does_not_use_python_yaml() -> None:
    """Per docs/invariants.md, hooks must not use `import yaml`."""
    body = HOOK.read_text(encoding="utf-8")
    assert "import yaml" not in body, (
        "enforce-inbox-monitor-after-pr.sh must not use `import yaml`. "
        "See docs/invariants.md and plugins/cloglog/hooks/lib/parse-yaml-scalar.sh."
    )


def test_hook_does_not_silently_pass_on_ps_failure() -> None:
    """Hook must exit 2 (not 0) when ps itself fails."""
    # Create a fake ps that exits with error
    import shutil

    bin_dir = Path("/tmp") / "fakebin_ps_fail"
    bin_dir.mkdir(exist_ok=True)
    ps_script = bin_dir / "ps"
    ps_script.write_text("#!/bin/bash\nexit 1\n")
    ps_script.chmod(0o755)
    git_path = shutil.which("git")
    if git_path and not (bin_dir / "git").exists():
        (bin_dir / "git").symlink_to(git_path)

    # Need a real git repo for the hook to get past git resolution
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        subprocess.run(["git", "init", str(tmp)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp), "commit", "--allow-empty", "-m", "init"],
            check=True,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        payload = _make_payload("gh pr create", cwd=tmp, tool_response=FAKE_PR_URL)
        result = _run_hook(
            payload,
            cwd=tmp,
            env_extra={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
        )
    assert result.returncode == 2, (
        "Hook must exit 2 (not 0) when ps fails — silent auto-pass on "
        "inspection failure would let the rule be bypassed by breaking ps."
    )
    assert result.stderr != "", "Hook must emit a warning when ps fails."
