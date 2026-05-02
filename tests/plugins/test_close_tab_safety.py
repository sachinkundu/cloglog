"""T-339 pin: bare ``zellij action close-tab`` is forbidden in close-wave
and reconcile flows because it closes the *focused* tab — historically
the supervisor's own tab. Callers MUST route through
``plugins/cloglog/hooks/lib/close-zellij-tab.sh``, which resolves the
target by name and refuses (exit 2) when it would close the focused tab.

Pre-T-339 the close-wave Step 5c block paired ``query-tab-names`` with a
bare ``close-tab``; the reconcile teardown did the same. Both killed the
supervisor twice in production. The regression mode that matters is
either:

- a future edit that re-introduces a literal ``zellij action close-tab``
  *not* immediately followed by ``--tab-id``, or
- an edit that drops the helper invocation entirely.

These pins guard both shapes.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = REPO_ROOT / "plugins/cloglog/hooks/lib/close-zellij-tab.sh"
CLOSE_WAVE = REPO_ROOT / "plugins/cloglog/skills/close-wave/SKILL.md"
RECONCILE = REPO_ROOT / "plugins/cloglog/skills/reconcile/SKILL.md"
WORKTREE_REMOVE = REPO_ROOT / "plugins/cloglog/hooks/worktree-remove.sh"


# Match `zellij action close-tab` NOT followed by `-` (so `--tab-id`,
# `--help`, `-t` are allowed). The forbidden shape is a bare
# `close-tab` that takes the focused tab.
BARE_CLOSE_TAB = re.compile(
    r"zellij\s+action\s+close-tab(?!\S)(?!\s+-)",
)


def _read(path: Path) -> str:
    assert path.exists(), f"{path} missing"
    return path.read_text(encoding="utf-8")


def test_helper_exists_and_executable() -> None:
    assert HELPER.exists(), f"{HELPER} missing — close-wave/reconcile depend on it"
    mode = HELPER.stat().st_mode
    assert mode & stat.S_IXUSR, f"{HELPER} must be executable"


def test_helper_has_focused_tab_guard() -> None:
    body = _read(HELPER)
    # Guard signal: helper compares target tab id to current tab id and exits 2.
    assert "current-tab-info" in body, (
        "helper must read current-tab-info to guard against closing the focused tab"
    )
    assert "exit 2" in body, "helper must exit 2 when refusing to close the focused tab"
    # Helper itself is the one place a tab-id-scoped close is allowed.
    assert "close-tab --tab-id" in body or "close-tab-by-id" in body, (
        "helper must close by tab id, not by name or by focus"
    )


def test_close_wave_skill_routes_through_helper() -> None:
    body = _read(CLOSE_WAVE)
    assert "close-zellij-tab.sh" in body, (
        "close-wave Step 5c must call the close-zellij-tab.sh helper, "
        "not invoke `zellij action close-tab` directly (T-339)"
    )
    bare = BARE_CLOSE_TAB.findall(body)
    assert not bare, (
        f"close-wave SKILL.md must not contain bare `zellij action close-tab` "
        f"(focused-tab killer). Found: {bare}. Use the helper or "
        f"`close-tab --tab-id <id>` after a guard."
    )


def test_reconcile_skill_routes_through_helper() -> None:
    body = _read(RECONCILE)
    assert "close-zellij-tab.sh" in body, (
        "reconcile teardown must call the close-zellij-tab.sh helper (T-339)"
    )
    bare = BARE_CLOSE_TAB.findall(body)
    assert not bare, (
        f"reconcile SKILL.md must not contain bare `zellij action close-tab`. Found: {bare}."
    )


def test_worktree_remove_routes_through_helper() -> None:
    body = _read(WORKTREE_REMOVE)
    assert "close-zellij-tab.sh" in body, (
        "worktree-remove.sh must call the close-zellij-tab.sh helper (T-339)"
    )
    bare = BARE_CLOSE_TAB.findall(body)
    assert not bare, (
        f"worktree-remove.sh must not contain bare `zellij action close-tab`. Found: {bare}."
    )


def test_helper_runtime_guard_refuses_focused_tab(tmp_path: Path) -> None:
    """Smoke-test the helper's guard with a fake `zellij` shim on PATH.

    Simulates: list-tabs returns a tab named `wt-fake` with TAB_ID 7,
    current-tab-info reports id 7. The helper must exit 2 and must NOT
    invoke `close-tab`.
    """
    import os
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "close-was-called"

    shim = bin_dir / "zellij"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'MARKER="{marker}"\n'
        'case "$*" in\n'
        '  "action list-tabs")\n'
        '    printf "TAB_ID\\tPOSITION\\tNAME\\n7\\t2\\twt-fake\\n";;\n'
        '  "action current-tab-info")\n'
        '    printf "name: wt-fake\\nid: 7\\nposition: 2\\n";;\n'
        '  "action close-tab"*)\n'
        '    : > "$MARKER"; exit 0;;\n'
        "  *) exit 0;;\n"
        "esac\n"
    )
    shim.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["ZELLIJ"] = "1"

    result = subprocess.run(
        ["bash", str(HELPER), "wt-fake"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, (
        f"helper should exit 2 when target tab is focused, got "
        f"{result.returncode}; stderr={result.stderr!r}"
    )
    assert not marker.exists(), (
        "helper invoked `zellij action close-tab` even though target was "
        "the focused tab — guard is broken"
    )


def test_helper_runtime_closes_unfocused_tab(tmp_path: Path) -> None:
    """When target tab is NOT focused, helper must close it via --tab-id."""
    import os
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "close-args"

    shim = bin_dir / "zellij"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'LOG="{log}"\n'
        'case "$*" in\n'
        '  "action list-tabs")\n'
        '    printf "TAB_ID\\tPOSITION\\tNAME\\n0\\t0\\tcloglog\\n7\\t2\\twt-fake\\n";;\n'
        '  "action current-tab-info")\n'
        '    printf "name: cloglog\\nid: 0\\nposition: 0\\n";;\n'
        '  "action close-tab "*)\n'
        '    echo "$*" > "$LOG"; exit 0;;\n'
        "  *) exit 0;;\n"
        "esac\n"
    )
    shim.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["ZELLIJ"] = "1"

    result = subprocess.run(
        ["bash", str(HELPER), "wt-fake"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"helper should exit 0 on successful close, got {result.returncode}; "
        f"stderr={result.stderr!r}"
    )
    assert log.exists(), "helper did not invoke `zellij action close-tab`"
    args = log.read_text().strip()
    assert "--tab-id 7" in args, f"helper must close by tab id 7, got args: {args!r}"


def test_helper_no_op_when_not_in_zellij(tmp_path: Path) -> None:
    """When ZELLIJ is unset, helper must exit 0 silently — many callers
    invoke it from non-tty contexts (CI, hooks) where zellij isn't running.
    """
    import os
    import subprocess

    env = os.environ.copy()
    env.pop("ZELLIJ", None)

    result = subprocess.run(
        ["bash", str(HELPER), "wt-fake"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"helper should be a no-op outside zellij, got {result.returncode}; "
        f"stderr={result.stderr!r}"
    )


def test_helper_idempotent_when_tab_absent(tmp_path: Path) -> None:
    """When no tab matches the name, helper must exit 0 — caller treats
    teardown as already-done.
    """
    import os
    import subprocess

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "zellij"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  "action list-tabs")\n'
        '    printf "TAB_ID\\tPOSITION\\tNAME\\n0\\t0\\tcloglog\\n";;\n'
        '  "action current-tab-info")\n'
        '    printf "name: cloglog\\nid: 0\\nposition: 0\\n";;\n'
        "  *) exit 0;;\n"
        "esac\n"
    )
    shim.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["ZELLIJ"] = "1"

    result = subprocess.run(
        ["bash", str(HELPER), "wt-gone"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"helper should exit 0 when tab is absent, got {result.returncode}"
    )
