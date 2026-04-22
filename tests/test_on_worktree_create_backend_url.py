"""Regression guard: T-259.

`.cloglog/on-worktree-create.sh`'s `_resolve_backend_url` MUST parse
`backend_url` out of `.cloglog/config.yaml` with `grep`+`sed`, never with
`python3 -c 'import yaml'`. The system `python3` this hook runs under
typically lacks `pyyaml` (the project's pyyaml lives in the uv venv, not
the global python), so the previous snippet silently swallowed
`ImportError` and returned the `http://localhost:8000` default — the
subsequent close-off-task POST then landed on port 8000 even when the
config declares `127.0.0.1:8001`, producing an HTTP 000 WARN that looked
transient but actually meant the task never reached the board.

Authoritative CLAUDE.md rule: "Hook scripts must parse `.cloglog/config.yaml`
with `grep`+`sed`, never `python3 -c 'import yaml'`."
Precedent:       `plugins/cloglog/hooks/agent-shutdown.sh:62-74`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".cloglog" / "on-worktree-create.sh"


@pytest.fixture
def stub_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Scratch repo layout with a stub `scripts/worktree-infra.sh`.

    Returns (repo_root, worktree_path). The hook's `REPO_ROOT` is derived
    from its own path (`"$(dirname "$0")/.."`), so it finds
    `${repo_root}/.cloglog/config.yaml` and `${repo_root}/scripts/worktree-infra.sh`.
    """
    repo = tmp_path / "repo"
    (repo / ".cloglog").mkdir(parents=True)
    shutil.copy(HOOK, repo / ".cloglog" / "on-worktree-create.sh")
    (repo / ".cloglog" / "on-worktree-create.sh").chmod(0o755)

    scripts = repo / "scripts"
    scripts.mkdir()
    # Stub infra up/down so the hook does not try to bring a real database
    # or write .env files.
    (scripts / "worktree-infra.sh").write_text("#!/bin/bash\nexit 0\n")
    (scripts / "worktree-infra.sh").chmod(0o755)

    wt = tmp_path / "wt"
    wt.mkdir()
    return repo, wt


def _run_hook(repo: Path, wt: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with a controlled env.

    `CLOGLOG_API_KEY` is unset and `HOME` points at an empty dir so
    `_resolve_api_key` returns empty and the close-off-task curl block is
    skipped — keeps the test hermetic (no network).
    """
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "WORKTREE_PATH": str(wt),
        "WORKTREE_NAME": "wt-test",
    }
    return subprocess.run(
        ["bash", str(repo / ".cloglog" / "on-worktree-create.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_resolve_backend_url_reads_non_default_port_from_config(
    stub_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """When `backend_url` in config.yaml is `http://127.0.0.1:8001`,
    the hook MUST resolve that exact URL — not fall back to
    `http://localhost:8000`. This is the T-259 core bug: prior code
    silently returned the default on any host missing pyyaml."""
    repo, wt = stub_repo
    (repo / ".cloglog" / "config.yaml").write_text(
        "project: test\nbackend_url: http://127.0.0.1:8001\n"
    )

    result = _run_hook(repo, wt, tmp_path / "empty-home")
    assert result.returncode == 0, f"hook exited non-zero:\n{result.stderr}"

    assert "backend_url=http://127.0.0.1:8001" in result.stderr, (
        "hook did not resolve the configured backend_url; stderr was:\n" + result.stderr
    )
    assert "localhost:8000" not in result.stderr, (
        "regression: silent fallback to localhost:8000 even when config.yaml "
        "declares a different backend_url. stderr:\n" + result.stderr
    )


def test_resolve_backend_url_falls_back_to_default_when_key_absent(
    stub_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """If `backend_url` is missing from config.yaml, the hook falls back to
    `http://localhost:8000` — the documented default. Keeps behaviour
    identical to the pre-T-259 code on the no-override path."""
    repo, wt = stub_repo
    (repo / ".cloglog" / "config.yaml").write_text("project: test\n")

    result = _run_hook(repo, wt, tmp_path / "empty-home")
    assert result.returncode == 0, f"hook exited non-zero:\n{result.stderr}"

    assert "backend_url=http://localhost:8000" in result.stderr, result.stderr


def test_resolve_backend_url_strips_trailing_comment_and_quotes(
    stub_repo: tuple[Path, Path], tmp_path: Path
) -> None:
    """The grep+sed pattern from `agent-shutdown.sh:62-74` strips a
    trailing `# …` comment and surrounding quotes. Pin that behaviour
    here so a future edit that deletes either sed stage breaks the test,
    not the runtime."""
    repo, wt = stub_repo
    (repo / ".cloglog" / "config.yaml").write_text(
        'project: test\nbackend_url: "http://127.0.0.1:9999"  # dev override\n'
    )

    result = _run_hook(repo, wt, tmp_path / "empty-home")
    assert result.returncode == 0, f"hook exited non-zero:\n{result.stderr}"

    assert "backend_url=http://127.0.0.1:9999" in result.stderr, result.stderr


def test_hook_does_not_invoke_python_yaml(stub_repo: tuple[Path, Path], tmp_path: Path) -> None:
    """Protect the CLAUDE.md rule at the source level. A future edit that
    re-introduces `import yaml` inside the hook is the bug — this test
    trips before the runtime does. Only non-comment lines are scanned so
    that prose mentioning the anti-pattern is allowed."""
    repo, _wt = stub_repo
    body = (repo / ".cloglog" / "on-worktree-create.sh").read_text()
    code_lines = [line for line in body.splitlines() if not line.lstrip().startswith("#")]
    offenders = [line for line in code_lines if "import yaml" in line or "yaml.safe_load" in line]
    assert not offenders, (
        "on-worktree-create.sh must not parse config.yaml via `python3 -c "
        "'import yaml'` — system python3 typically lacks pyyaml. Use the "
        "grep+sed pattern from plugins/cloglog/hooks/agent-shutdown.sh:62-74.\n"
        f"Offending lines: {offenders}"
    )
