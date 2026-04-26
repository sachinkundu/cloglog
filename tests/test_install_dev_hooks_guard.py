"""Backstop: T-301 / T-prod-8.

`scripts/install-dev-hooks.sh` writes a per-clone `pre-commit` hook
that rejects commits to `main` unless `ALLOW_MAIN_COMMIT=1` is set.
The hook is the dev-clone-only safety net behind the close-wave /
reconcile branch+PR flow restored in T-prod-7: without it, a stray
`git commit` on `main` would silently leak into worktrees branched
from local `main`.

These tests run the installer in a temp git repo, exercise the guard
in both rejection and override paths, and assert the failure message
mentions the `ALLOW_MAIN_COMMIT` override so an operator who hits the
block can find the escape hatch.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts/install-dev-hooks.sh"


def _run(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command capturing stdout+stderr as text."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture()
def temp_repo(tmp_path: Path) -> Path:
    """Initialize a fresh git repo with an initial commit on a non-main
    branch. The hook is installed but starts inert until HEAD moves to
    `main` — keeping the fixture self-contained."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], cwd=repo).check_returncode()
    _run(["git", "config", "user.email", "test@example.invalid"], cwd=repo).check_returncode()
    _run(["git", "config", "user.name", "Test"], cwd=repo).check_returncode()
    _run(["git", "config", "commit.gpgsign", "false"], cwd=repo).check_returncode()
    # Seed an initial commit on `main` so subsequent commits are not "root commits."
    # Bypass the guard for the seed by setting ALLOW_MAIN_COMMIT=1 BEFORE
    # the installer runs; the hook is not installed yet anyway, so this
    # is belt-and-braces.
    (repo / "README.md").write_text("seed\n")
    _run(["git", "add", "README.md"], cwd=repo).check_returncode()
    _run(["git", "commit", "-m", "seed"], cwd=repo).check_returncode()
    return repo


def test_installer_creates_pre_commit_hook(temp_repo: Path) -> None:
    """The script writes `.git/hooks/pre-commit` and marks it
    executable. Without that file the hook is inert and the guard
    fails open."""
    result = _run(["bash", str(INSTALLER)], cwd=temp_repo)
    assert result.returncode == 0, (
        f"install-dev-hooks.sh exited {result.returncode}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    hook = temp_repo / ".git/hooks/pre-commit"
    assert hook.exists(), (
        "Installer must create .git/hooks/pre-commit. The dev-clone "
        "guard is the safety net for the wt-* branch + PR flow; a "
        "missing hook fails open and lets direct-`main` commits through."
    )
    assert os.access(hook, os.X_OK), (
        "Installed pre-commit hook must be executable; otherwise git "
        "skips it silently and the guard never fires."
    )


def test_guard_blocks_direct_commit_on_main(temp_repo: Path) -> None:
    """A `git commit` on `main` without the override must exit non-zero
    and print a message naming the override env var so the operator
    knows the escape hatch."""
    _run(["bash", str(INSTALLER)], cwd=temp_repo).check_returncode()
    (temp_repo / "file.txt").write_text("change\n")
    _run(["git", "add", "file.txt"], cwd=temp_repo).check_returncode()
    result = _run(["git", "commit", "-m", "should be blocked"], cwd=temp_repo)
    assert result.returncode != 0, (
        "Commit on main without ALLOW_MAIN_COMMIT=1 must fail. The "
        "T-prod-8 guard exists precisely to make this mistake loud — "
        "if the commit succeeds, the dev clone has lost its safety net."
    )
    combined = result.stdout + result.stderr
    assert "ALLOW_MAIN_COMMIT" in combined, (
        "Guard failure message must mention ALLOW_MAIN_COMMIT so the "
        "operator knows the override exists. Without that hint they "
        "will either improvise (e.g. `--no-verify`, which we never want "
        "to encourage) or get stuck."
    )


def test_guard_allows_commit_when_override_set(temp_repo: Path) -> None:
    """The override exists for emergency-rollback cherry-picks. With
    `ALLOW_MAIN_COMMIT=1` set, the same commit must succeed."""
    _run(["bash", str(INSTALLER)], cwd=temp_repo).check_returncode()
    (temp_repo / "file.txt").write_text("change\n")
    _run(["git", "add", "file.txt"], cwd=temp_repo).check_returncode()
    result = _run(
        ["git", "commit", "-m", "override-allowed"],
        cwd=temp_repo,
        env={"ALLOW_MAIN_COMMIT": "1"},
    )
    assert result.returncode == 0, (
        "Commit on main with ALLOW_MAIN_COMMIT=1 must succeed. The "
        "override is the documented escape hatch for emergency-rollback "
        f"cherry-picks; if it does not work, the rollback path is "
        f"broken. stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_guard_allows_commit_on_non_main_branch(temp_repo: Path) -> None:
    """The guard targets `main` only. Commits on `wt-*` and any other
    branch must pass through untouched."""
    _run(["bash", str(INSTALLER)], cwd=temp_repo).check_returncode()
    _run(["git", "checkout", "-b", "wt-example"], cwd=temp_repo).check_returncode()
    (temp_repo / "file.txt").write_text("change\n")
    _run(["git", "add", "file.txt"], cwd=temp_repo).check_returncode()
    result = _run(["git", "commit", "-m", "on a wt-* branch"], cwd=temp_repo)
    assert result.returncode == 0, (
        "Commits on non-main branches must NOT be blocked. Every "
        "agent's standard flow is `wt-* branch + PR`; if the guard "
        "fires there, the entire fleet stops working. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_installer_is_idempotent(temp_repo: Path) -> None:
    """Re-running the installer must overwrite cleanly with no
    error. Operators run it after pulling a hook update, and the
    second-run failure mode (e.g., refusing to overwrite) would push
    them toward manually editing the hook — exactly the drift the
    installer prevents."""
    first = _run(["bash", str(INSTALLER)], cwd=temp_repo)
    assert first.returncode == 0
    second = _run(["bash", str(INSTALLER)], cwd=temp_repo)
    assert second.returncode == 0, (
        f"Re-running install-dev-hooks.sh must succeed. "
        f"stdout={second.stdout!r} stderr={second.stderr!r}"
    )
