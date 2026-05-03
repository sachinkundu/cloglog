"""Regression guard: T-257.

`.cloglog/on-worktree-create.sh` must install `mcp-server/` node modules
on ANY worktree whose checkout contains `mcp-server/package.json`, not
only worktrees whose `WORKTREE_NAME` starts with `wt-mcp`. The previous
narrow guard shipped broken for `wt-c2-mcp-rebuild` under T-244: the
worktree name did not match `wt-mcp*`, so `node_modules/` was absent and
the first `make quality` blew up on `npx tsc` with "This is not the tsc
command you are looking for". The install is cheap with a warm cache;
trading the second for zero foot-guns is the correct call.

The tests run the real hook against a scratch repo layout, PATH-shimming
`npm` to a stub that records its argv — no real network or npm registry
contact.
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
def stub_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Scratch repo layout + a PATH shim dir where a stub `npm` will live.

    Returns (repo_root, worktree_path, shim_dir). The stub `npm` writes
    each invocation's argv to `shim_dir/npm.log`, one line per call.
    """
    repo = tmp_path / "repo"
    (repo / ".cloglog").mkdir(parents=True)
    shutil.copy(HOOK, repo / ".cloglog" / "on-worktree-create.sh")
    (repo / ".cloglog" / "on-worktree-create.sh").chmod(0o755)
    (repo / ".cloglog" / "config.yaml").write_text("project: test\n")

    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "worktree-infra.sh").write_text("#!/bin/bash\nexit 0\n")
    (scripts / "worktree-infra.sh").chmod(0o755)

    wt = tmp_path / "wt"
    wt.mkdir()

    shim = tmp_path / "shim"
    shim.mkdir()
    # Stub npm: record argv to npm.log and exit 0. The hook cd's into
    # mcp-server/ before calling npm, so the log lives at an absolute
    # path passed via env.
    (shim / "npm").write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$NPM_LOG"\nexit 0\n')
    (shim / "npm").chmod(0o755)
    # T-378 stub curl: the close-off-task POST is now fail-loud, so the
    # hook needs a real-looking 201 response or it aborts before reaching
    # the npm-install branch this test exercises. The stub writes the body
    # file curl would have written and prints "201" so the hook's HTTP-code
    # capture parses cleanly.
    (shim / "curl").write_text(
        "#!/bin/bash\n"
        "# Find the -o argument and touch the output file so the hook's\n"
        "# `[[ -s ... ]]` check on the body file is well-defined.\n"
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
    repo: Path, wt: Path, shim: Path, home: Path, worktree_name: str
) -> subprocess.CompletedProcess[str]:
    """Invoke the hook with npm PATH-shimmed to a logger."""
    npm_log = shim / "npm.log"
    # Ensure fresh log each run so assertions are unambiguous.
    npm_log.unlink(missing_ok=True)
    env = {
        "PATH": f"{shim}:{os.environ['PATH']}",
        "HOME": str(home),
        "WORKTREE_PATH": str(wt),
        "WORKTREE_NAME": worktree_name,
        "NPM_LOG": str(npm_log),
        # T-378 fail-loud: the close-off-task POST aborts on missing API
        # key. Provide a sentinel value so the curl shim is exercised.
        "CLOGLOG_API_KEY": "stub-key-for-tests",
    }
    return subprocess.run(
        ["bash", str(repo / ".cloglog" / "on-worktree-create.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _npm_calls(shim: Path) -> list[str]:
    log = shim / "npm.log"
    if not log.exists():
        return []
    return [line for line in log.read_text().splitlines() if line]


def test_npm_install_runs_on_non_wt_mcp_branch_when_package_json_present(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """The T-257 core fix: WORKTREE_NAME=wt-sanity-check (does NOT match
    `wt-mcp*`) but `mcp-server/package.json` exists. The hook MUST run
    `npm install`. Pre-T-257 this silently skipped and the next
    `make quality` failed on `npx tsc`."""
    repo, wt, shim = stub_repo
    # mcp-server/ lives under the WORKTREE checkout (where the hook
    # `cd`s before the install check), NOT under the main repo root.
    mcp = wt / "mcp-server"
    mcp.mkdir()
    (mcp / "package.json").write_text('{"name": "test-mcp", "version": "0.0.0"}\n')

    result = _run_hook(repo, wt, shim, tmp_path / "home", "wt-sanity-check")
    assert result.returncode == 0, f"hook exited non-zero:\n{result.stderr}"
    assert _npm_calls(shim) == ["install"], (
        "hook must call `npm install` once when mcp-server/package.json "
        f"exists, even on a non-wt-mcp* branch. Calls: {_npm_calls(shim)!r}"
    )


def test_npm_install_still_runs_on_wt_mcp_branch(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Legacy wt-mcp* worktrees still trigger the install — T-257 only
    broadens, never narrows. Guards against a regression where someone
    inverts the condition."""
    repo, wt, shim = stub_repo
    # mcp-server/ lives under the WORKTREE checkout (where the hook
    # `cd`s before the install check), NOT under the main repo root.
    mcp = wt / "mcp-server"
    mcp.mkdir()
    (mcp / "package.json").write_text('{"name": "test-mcp", "version": "0.0.0"}\n')

    result = _run_hook(repo, wt, shim, tmp_path / "home", "wt-mcp-rebuild")
    assert result.returncode == 0, f"hook exited non-zero:\n{result.stderr}"
    assert _npm_calls(shim) == ["install"], _npm_calls(shim)


def test_npm_install_skipped_when_no_mcp_server_dir(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Downstream projects that adopt this plugin without an MCP server
    must not try to install nonexistent deps. The package.json guard
    keeps those projects quiet."""
    repo, wt, shim = stub_repo
    # No mcp-server/ dir at all.
    result = _run_hook(repo, wt, shim, tmp_path / "home", "wt-anything")
    assert result.returncode == 0, f"hook exited non-zero:\n{result.stderr}"
    assert _npm_calls(shim) == [], (
        f"hook must NOT call npm when mcp-server/ is absent. Calls: {_npm_calls(shim)!r}"
    )


def test_npm_install_skipped_when_mcp_dir_but_no_package_json(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """An empty `mcp-server/` dir with no manifest cannot be installed.
    Pin the `-f mcp-server/package.json` guard so a future narrowing
    to `-d mcp-server` alone does not resurrect a spurious npm call."""
    repo, wt, shim = stub_repo
    (wt / "mcp-server").mkdir()  # dir exists in the worktree, but no package.json
    result = _run_hook(repo, wt, shim, tmp_path / "home", "wt-something")
    assert result.returncode == 0, f"hook exited non-zero:\n{result.stderr}"
    assert _npm_calls(shim) == [], _npm_calls(shim)


def test_mcp_install_block_has_no_wt_mcp_name_guard(
    stub_repo: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Source-level guard: the mcp-server install block must not
    reference `wt-mcp` in a non-comment line. Catches a future edit
    that re-introduces the narrow branch-name guard. Per-file boolean,
    not a repo-wide count — an unrelated doc that mentions `wt-mcp*`
    never flips this test."""
    hook_text = HOOK.read_text()
    # Walk lines; isolate the mcp-server block.
    lines = hook_text.splitlines()
    mcp_block: list[str] = []
    in_block = False
    for line in lines:
        if "mcp-server/package.json" in line and line.lstrip().startswith("if"):
            in_block = True
        if in_block:
            mcp_block.append(line)
            if line.strip() == "fi":
                break
    assert mcp_block, (
        f"could not locate the mcp-server install block in {HOOK} — did someone rename the guard?"
    )
    offenders = [
        line for line in mcp_block if not line.lstrip().startswith("#") and "wt-mcp" in line
    ]
    assert not offenders, (
        "mcp-server install block re-introduced a `wt-mcp` branch-name "
        f"guard. Offending lines: {offenders}"
    )
