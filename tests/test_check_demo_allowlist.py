"""Pin test for the silent-failure invariant:

> ``scripts/check-demo.sh`` auto-exempts a branch when every changed file
> matches the static allowlist (``docs/``, ``CLAUDE.md``, ``.claude/``,
> ``.cloglog/``, ``scripts/``, ``.github/``, ``tests/``, ``Makefile``,
> ``plugins/*/hooks/``, ``pyproject.toml``, ``ruff.toml``, ``*.lock``).
> A single file outside that set forces the demo gate.

The rule lives in ``docs/invariants.md`` § Demo gate allowlist.

Regression this guards: the gate previously listed only ``tests/e2e/``
(not all tests), no ``Makefile``, no ``.cloglog/``. Agents who edited
``Makefile`` or added unit tests were forced to synthesise a
Showboat demo against grep/awk output because the gate flipped to
"code changed." See ``docs/superpowers/specs/2026-04-24-demo-classifier-design.md``
for the full rationale.

The test fabricates two temporary git repos — one entirely allowlisted
(must exit 0), one with a single ``src/`` file (must exit non-zero) —
and runs the real ``scripts/check-demo.sh`` against each. Any future
regex edit that drops a listed path or fails to match a new allowlisted
path trips this test.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_DEMO_SH = REPO_ROOT / "scripts" / "check-demo.sh"


def _run(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _init_repo(tmp_path: Path) -> dict[str, str]:
    """Initialise a git repo with one commit on ``main`` and a shadow
    ``origin/main`` ref so ``scripts/check-demo.sh``'s merge-base lookup
    resolves. Returns the env dict callers should pass to subsequent
    git invocations."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        # Strip inherited ambient git-repo context from CWD.
        "GIT_DIR": str(tmp_path / ".git"),
        "GIT_WORK_TREE": str(tmp_path),
    }
    _run(["git", "init", "-b", "main", "."], tmp_path, env).check_returncode()
    # Drop GIT_DIR / GIT_WORK_TREE now that the repo exists — later git
    # commands should use the local repo via CWD only.
    env.pop("GIT_DIR")
    env.pop("GIT_WORK_TREE")
    (tmp_path / "README.md").write_text("# test\n")
    _run(["git", "add", "README.md"], tmp_path, env).check_returncode()
    _run(["git", "commit", "-m", "initial"], tmp_path, env).check_returncode()
    # Fabricate an ``origin/main`` ref pointing at the initial commit so
    # the script's ``git merge-base origin/main HEAD`` call resolves.
    head_sha = _run(["git", "rev-parse", "HEAD"], tmp_path, env).stdout.strip()
    _run(
        ["git", "update-ref", "refs/remotes/origin/main", head_sha],
        tmp_path,
        env,
    ).check_returncode()
    _run(["git", "checkout", "-b", "feature-branch"], tmp_path, env).check_returncode()
    return env


def _commit(repo: Path, env: dict[str, str], relpath: str, contents: str = "x\n") -> None:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents)
    _run(["git", "add", relpath], repo, env).check_returncode()
    _run(["git", "commit", "-m", f"touch {relpath}"], repo, env).check_returncode()


ALLOWLISTED_PATHS = [
    "docs/foo.md",
    "CLAUDE.md",
    ".claude/agents/new-agent.md",
    ".cloglog/config.yaml",
    "scripts/helper.sh",
    ".github/workflows/ci.yml",
    "tests/test_unit.py",
    "tests/e2e/test_browser.py",
    "Makefile",
    "plugins/cloglog/hooks/new-hook.sh",
    "pyproject.toml",
    "ruff.toml",
    "uv.lock",
]


@pytest.mark.parametrize("relpath", ALLOWLISTED_PATHS)
def test_allowlisted_change_auto_exempts(tmp_path: Path, relpath: str) -> None:
    env = _init_repo(tmp_path)
    _commit(tmp_path, env, relpath)
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode == 0, (
        f"check-demo.sh rejected an allowlisted change ({relpath}).\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "Docs-only branch" in result.stdout, (
        f"Expected docs-only short-circuit message for allowlisted change ({relpath}).\n"
        f"stdout: {result.stdout!r}"
    )


def test_src_change_is_not_allowlisted(tmp_path: Path) -> None:
    """A single file outside the allowlist must force the gate."""
    env = _init_repo(tmp_path)
    _commit(tmp_path, env, "src/gateway/routes.py", "def handler():\n    return 1\n")
    # docs/demos/ does not exist, so the script short-circuits with
    # "demo system not yet initialized" — still exit 0, but we assert
    # the allowlist branch was NOT taken. Create docs/demos/ so we hit
    # the actual "no demo found" error path.
    (tmp_path / "docs" / "demos").mkdir(parents=True, exist_ok=True)
    _run(["git", "add", "docs/demos"], tmp_path, env)  # empty dir — git ignores
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode != 0, (
        "check-demo.sh auto-exempted a src/ change — the allowlist regex "
        "is too permissive.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    # Must have rejected because the src/ file forced the gate, not because
    # of any unrelated error.
    combined = result.stdout + result.stderr
    assert "No demo found" in combined, (
        "Expected the allowlist to reject src/ and the script to fall "
        "through to the 'no demo found' error.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_mixed_allowlisted_and_src_forces_gate(tmp_path: Path) -> None:
    """Any single non-allowlisted file among many allowlisted ones must
    still force the gate — ``grep -vE`` must match the non-allowlisted
    line and count as CODE_CHANGES."""
    env = _init_repo(tmp_path)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "note.md").write_text("note\n")
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "real.py").write_text("x = 1\n")
    _run(["git", "add", "docs/note.md", "src/real.py"], tmp_path, env).check_returncode()
    _run(["git", "commit", "-m", "mix"], tmp_path, env).check_returncode()
    (tmp_path / "docs" / "demos").mkdir(parents=True, exist_ok=True)
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode != 0, (
        "A diff containing docs/ + src/ auto-exempted — the allowlist "
        "must only exempt when ALL changed files match.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
