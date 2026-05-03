"""Pin test: T-378 (codex review session 2/5).

`plugins/cloglog/hooks/worktree-create.sh` is the WorktreeCreate-event
hook. It registers the agent and then runs the project-specific
``${CONFIG_DIR}/on-worktree-create.sh``. T-378 made the bootstrap script
fail loud on missing credentials / non-201 close-off-task — but if this
WorktreeCreate caller suppresses the bootstrap's exit status (the
pre-T-378 ``|| true`` shape), the fail-loud guarantee is silently
discarded on the WorktreeCreate path and the worktree ships without a
close-off task anyway.

This file pins the propagation contract two ways:

1. **Static** — the line that invokes ``on-worktree-create.sh`` must not
   end with ``|| true`` (or any other unconditional success-coerce).
2. **Dynamic** — running the hook against a stub bootstrap that exits 1
   produces a non-zero exit from the WorktreeCreate hook itself.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = REPO_ROOT / "plugins/cloglog/hooks/worktree-create.sh"


def _read_hook() -> str:
    assert HOOK.exists(), f"{HOOK} missing"
    return HOOK.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static pin: the bootstrap call must not be suppressed.
# ---------------------------------------------------------------------------


def test_bootstrap_invocation_is_not_suppressed() -> None:
    """The line(s) that invoke ``on-worktree-create.sh`` must not be wrapped
    in ``|| true`` (or any equivalent unconditional success-coerce). T-378
    makes the bootstrap fail loud; suppressing that here silently
    re-introduces the silent-partial-setup bug on the WorktreeCreate path.
    """
    body = _read_hook()
    # Locate the on-worktree-create.sh invocation block. Match every line
    # from the `if` opening that gates the script down to its `fi`.
    section = re.search(
        r"if \[\[.*on-worktree-create\.sh.*\]\]; then(.*?)\nfi",
        body,
        flags=re.DOTALL,
    )
    assert section, (
        "Could not locate the `on-worktree-create.sh` invocation guard in "
        f"{HOOK}. The block layout may have changed — re-anchor this test."
    )
    block = section.group(1)
    # `|| true` after the script call (any whitespace / line continuation in
    # between) is the regression. Match conservatively.
    assert not re.search(r"on-worktree-create\.sh[\"]?\s*\\?\s*\|\|\s*true", block), (
        "WorktreeCreate hook must NOT swallow `on-worktree-create.sh`'s "
        "non-zero exit. T-378's fail-loud guarantee depends on this caller "
        "propagating the status. Capture $? and `exit $status` if you need "
        "a custom diagnostic, but never `|| true`."
    )


# ---------------------------------------------------------------------------
# Dynamic pin: a failing bootstrap must surface as a non-zero hook exit.
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_repo_and_hook(tmp_path: Path) -> tuple[Path, Path]:
    """Scratch tree with a config.yaml and a stub bootstrap script that
    exits non-zero. Returns (hook_path, repo_root).

    The hook is copied alongside its lib directory so its `source` of
    `parse-yaml-scalar.sh` and `resolve-api-key.sh` resolves.
    """
    # Lay out the plugin tree so the hook's source-relative lib lookups work.
    plugin_dir = tmp_path / "plugins/cloglog/hooks"
    plugin_dir.mkdir(parents=True)
    shutil.copy(HOOK, plugin_dir / "worktree-create.sh")
    (plugin_dir / "worktree-create.sh").chmod(0o755)
    lib_src = REPO_ROOT / "plugins/cloglog/hooks/lib"
    shutil.copytree(lib_src, plugin_dir / "lib")

    # Project repo with .cloglog/config.yaml and a stub on-worktree-create.sh.
    repo = tmp_path / "repo"
    (repo / ".cloglog").mkdir(parents=True)
    (repo / ".cloglog" / "config.yaml").write_text("project: alpha\n")
    bootstrap = repo / ".cloglog" / "on-worktree-create.sh"
    bootstrap.write_text(
        '#!/bin/bash\necho "[stub on-worktree-create] simulated FATAL" >&2\nexit 1\n'
    )
    bootstrap.chmod(0o755)

    return plugin_dir / "worktree-create.sh", repo


def test_hook_exits_nonzero_when_bootstrap_fails(
    stub_repo_and_hook: tuple[Path, Path], tmp_path: Path
) -> None:
    """End-to-end: feed the hook the WorktreeCreate JSON payload Claude
    sends, point CONFIG_DIR at the stub bootstrap that exits 1, and assert
    the hook exits non-zero rather than swallowing the failure."""
    hook, repo = stub_repo_and_hook
    # Make sure the hook does not try to register against a real backend:
    # the resolve_api_key helper returns empty when no env / credentials
    # files exist, and the curl block is gated on a non-empty key. HOME
    # points at an empty dir so no credentials are picked up.
    home = tmp_path / "empty-home"
    home.mkdir()
    payload = json.dumps({"worktree_path": str(repo)})
    result = subprocess.run(
        ["bash", str(hook)],
        input=payload,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, (
        "WorktreeCreate hook returned 0 even though the bootstrap script "
        f"exited 1. stderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    assert "FATAL" in result.stderr or "exited" in result.stderr, (
        "Hook should emit a diagnostic mentioning the bootstrap failure "
        "before propagating; missing diagnostic makes operator triage "
        f"harder. stderr:\n{result.stderr}"
    )
