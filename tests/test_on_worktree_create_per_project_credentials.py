"""Regression guard: T-378 / T-382.

After T-378 made `.cloglog/on-worktree-create.sh` fail loud on missing
CLOGLOG_API_KEY, the script's `_resolve_api_key` MUST honor the canonical
per-project credentials layout — env → `~/.cloglog/credentials.d/<slug>`
→ `~/.cloglog/credentials`. The PR #310 codex review caught that the
script only checked env + legacy global; on a multi-project host using
the documented `credentials.d/<slug>` setup (see
``docs/setup-credentials.md`` and ``plugins/cloglog/hooks/lib/resolve-api-key.sh``)
the script would `exit 1` even though valid credentials exist.

This test provisions ONLY `~/.cloglog/credentials.d/<slug>` (no env, no
legacy file) and asserts the hook reaches its happy-path exit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".cloglog" / "on-worktree-create.sh"
RESOLVER_LIB = REPO_ROOT / "plugins/cloglog/hooks/lib/resolve-api-key.sh"
PARSER_LIB = REPO_ROOT / "plugins/cloglog/hooks/lib/parse-yaml-scalar.sh"


@pytest.fixture
def stub_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Scratch repo layout that mirrors cloglog's ``.cloglog/`` + plugin
    lib paths so the script's `source` of `resolve-api-key.sh` resolves.

    Returns (repo_root, worktree_path, shim_dir).
    """
    repo = tmp_path / "repo"
    (repo / ".cloglog").mkdir(parents=True)
    shutil.copy(HOOK, repo / ".cloglog" / "on-worktree-create.sh")
    (repo / ".cloglog" / "on-worktree-create.sh").chmod(0o755)
    (repo / ".cloglog" / "config.yaml").write_text("project: alpha\n")

    # Mirror the plugin lib tree so the script can source the canonical
    # resolver from ${REPO_ROOT}/plugins/cloglog/hooks/lib/.
    lib_dir = repo / "plugins/cloglog/hooks/lib"
    lib_dir.mkdir(parents=True)
    shutil.copy(RESOLVER_LIB, lib_dir / "resolve-api-key.sh")
    shutil.copy(PARSER_LIB, lib_dir / "parse-yaml-scalar.sh")

    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "worktree-infra.sh").write_text("#!/bin/bash\nexit 0\n")
    (scripts / "worktree-infra.sh").chmod(0o755)

    wt = tmp_path / "wt"
    wt.mkdir()

    shim = tmp_path / "shim"
    shim.mkdir()
    # Stub curl: hand back HTTP 201 so the close-off-task POST succeeds.
    (shim / "curl").write_text(
        "#!/bin/bash\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  case "$1" in\n'
        '    -o) : > "$2"; shift 2 ;;\n'
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        'echo -n "201"\n'
    )
    (shim / "curl").chmod(0o755)
    return repo, wt, shim


def _run_hook(
    repo: Path,
    wt: Path,
    shim: Path,
    home: Path,
    *,
    inject_env_key: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{shim}:{os.environ['PATH']}",
        "HOME": str(home),
        "WORKTREE_PATH": str(wt),
        "WORKTREE_NAME": "wt-test",
    }
    if inject_env_key:
        env["CLOGLOG_API_KEY"] = "env-override-key"
    return subprocess.run(
        ["bash", str(repo / ".cloglog" / "on-worktree-create.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hook_succeeds_with_only_per_project_credentials_d_file(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """The PR #310 codex finding: with only ``~/.cloglog/credentials.d/<slug>``
    present (no env, no legacy global), the hook must reach happy-path
    exit. Pre-fix this aborted with FATAL because `_resolve_api_key`
    only checked env + legacy."""
    repo, wt, shim = stub_repo
    home = tmp_path / "home"
    creds_d = home / ".cloglog" / "credentials.d"
    creds_d.mkdir(parents=True)
    # Slug derived from config.yaml `project: alpha`.
    (creds_d / "alpha").write_text("CLOGLOG_API_KEY=per-project-key\n")
    (creds_d / "alpha").chmod(0o600)

    result = _run_hook(repo, wt, shim, home)
    assert result.returncode == 0, (
        f"hook exited non-zero despite per-project credentials.d/<slug> "
        f"being present:\n{result.stderr}"
    )
    assert "FATAL no CLOGLOG_API_KEY" not in result.stderr, (
        "hook should have resolved the per-project key; FATAL message "
        f"in stderr means the resolver missed it:\n{result.stderr}"
    )
    assert "close-off task filed" in result.stdout, (
        "hook should have reached the happy-path 'close-off task filed' "
        f"log line. stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_hook_succeeds_with_only_legacy_global_credentials(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Legacy single-project hosts that still rely on ``~/.cloglog/credentials``
    must keep working — T-382's per-project resolver falls through to the
    legacy file when no ``credentials.d/<slug>`` exists."""
    repo, wt, shim = stub_repo
    home = tmp_path / "home"
    cloglog_home = home / ".cloglog"
    cloglog_home.mkdir(parents=True)
    (cloglog_home / "credentials").write_text("CLOGLOG_API_KEY=legacy-global-key\n")
    (cloglog_home / "credentials").chmod(0o600)

    result = _run_hook(repo, wt, shim, home)
    assert result.returncode == 0, (
        f"hook exited non-zero with legacy global credentials present:\n{result.stderr}"
    )
    assert "close-off task filed" in result.stdout, result.stdout


def test_hook_aborts_when_no_credentials_anywhere(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Fail-loud baseline (T-378): with no env, no per-project file, and
    no legacy file, the hook must abort with FATAL — not silent-skip."""
    repo, wt, shim = stub_repo
    home = tmp_path / "empty-home"
    (home / ".cloglog").mkdir(parents=True)  # exists but empty

    result = _run_hook(repo, wt, shim, home)
    assert result.returncode != 0, (
        "hook should have aborted with no credentials anywhere; got exit 0:\n" + result.stderr
    )
    assert "FATAL no CLOGLOG_API_KEY" in result.stderr, (
        "FATAL message must name CLOGLOG_API_KEY so the operator can grep "
        f"for it. stderr:\n{result.stderr}"
    )
    assert "credentials.d/<project_slug>" in result.stderr, (
        "FATAL message must mention the per-project location so the "
        "operator knows where to add the key on multi-project hosts.\n"
        f"stderr:\n{result.stderr}"
    )
