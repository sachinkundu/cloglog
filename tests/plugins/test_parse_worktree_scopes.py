"""T-313 / Phase 0b: stdlib-only worktree_scopes parser + hook integration.

Pin tests for plugins/cloglog/hooks/lib/parse-worktree-scopes.py and the
retrofitted plugins/cloglog/hooks/protect-worktree-writes.sh hook.

The parser replaces a `python3 -c 'import yaml'` snippet that violated
docs/invariants.md:76 (system python3 plugin hooks run under typically
lacks PyYAML). The two halves are pinned together because either side
can regress independently — a parser that returns wrong-shaped data
silently disables the worktree write-guard, and a hook that stops
calling the parser silently disables it the same way.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PARSER = REPO_ROOT / "plugins/cloglog/hooks/lib/parse-worktree-scopes.py"
HOOK = REPO_ROOT / "plugins/cloglog/hooks/protect-worktree-writes.sh"


def _run_parser(
    cfg: Path,
    scope: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(PARSER), str(cfg), scope],
        capture_output=True,
        text=True,
        env=env,
    )


# --- parser shape tests ---------------------------------------------------


def test_parser_file_exists_and_is_executable() -> None:
    assert PARSER.exists(), f"{PARSER} missing"
    assert PARSER.stat().st_mode & 0o111, f"{PARSER} must be executable"
    body = PARSER.read_text(encoding="utf-8")
    assert "import yaml" not in body, (
        "parser must remain stdlib-only — `import yaml` defeats its entire purpose"
    )


def test_flow_style_list(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "worktree_scopes:\n"
        "  board: [src/board/, tests/board/, src/alembic/]\n"
        "  agent: [src/agent/]\n"
    )
    out = _run_parser(cfg, "board")
    assert out.returncode == 0, out.stderr
    assert out.stdout == "src/board/,tests/board/,src/alembic/"

    out = _run_parser(cfg, "agent")
    assert out.returncode == 0
    assert out.stdout == "src/agent/"


def test_block_style_list(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "worktree_scopes:\n"
        "  board:\n"
        "    - src/board/\n"
        "    - tests/board/\n"
        "  agent:\n"
        "    - src/agent/\n"
    )
    out = _run_parser(cfg, "board")
    assert out.returncode == 0, out.stderr
    assert out.stdout == "src/board/,tests/board/"


def test_prefix_match_falls_back_to_longest(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("worktree_scopes:\n  frontend: [frontend/]\n  frontend-auth: [frontend/auth/]\n")
    # Exact match wins over prefix.
    out = _run_parser(cfg, "frontend-auth")
    assert out.stdout == "frontend/auth/"
    # Unknown suffix falls back to the longest matching prefix.
    out = _run_parser(cfg, "frontend-auth-extra")
    assert out.stdout == "frontend/auth/"
    out = _run_parser(cfg, "frontend-misc")
    assert out.stdout == "frontend/"


def test_missing_scope_prints_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("worktree_scopes:\n  board: [src/board/]\n")
    out = _run_parser(cfg, "agent")
    assert out.returncode == 0
    assert out.stdout == ""


def test_missing_file_exits_nonzero(tmp_path: Path) -> None:
    out = _run_parser(tmp_path / "absent.yaml", "board")
    assert out.returncode == 3
    assert "config not found" in out.stderr


def test_extra_whitespace_and_comments_tolerated(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "# top-level comment\n"
        "project: cloglog\n"
        "\n"
        "worktree_scopes:\n"
        "  # nested comment\n"
        "  board: [src/board/, tests/board/]   # inline comment\n"
        "\n"
        "  agent:   \n"
        "    - src/agent/\n"
        "    - tests/agent/   # trailing comment\n"
        "\n"
        "trailing_top_level: ok\n"
    )
    assert _run_parser(cfg, "board").stdout == "src/board/,tests/board/"
    assert _run_parser(cfg, "agent").stdout == "src/agent/,tests/agent/"


def test_quoted_paths_are_unwrapped(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("worktree_scopes:\n  board: ['src/board/', \"tests/board/\"]\n")
    assert _run_parser(cfg, "board").stdout == "src/board/,tests/board/"


def test_no_worktree_scopes_section_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("project: cloglog\nbackend_url: http://x\n")
    out = _run_parser(cfg, "board")
    assert out.returncode == 0
    assert out.stdout == ""


@pytest.mark.parametrize(
    "body",
    [
        # Inline value on worktree_scopes itself — caller probably meant `{...}` but
        # we deliberately don't try to be helpful about anchors / inline maps.
        "worktree_scopes: this-is-a-string\n",
        # Block list item with no leading dash.
        "worktree_scopes:\n  board:\n    src/board/\n",
        # Flow value but missing closing bracket.
        "worktree_scopes:\n  board: [src/board/, tests/board/\n",
        # Duplicate key.
        "worktree_scopes:\n  board: [src/board/]\n  board: [src/agent/]\n",
    ],
)
def test_malformed_input_errors_loudly(tmp_path: Path, body: str) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(body)
    out = _run_parser(cfg, "board")
    assert out.returncode == 4, (
        f"expected parse error, got rc={out.returncode} stdout={out.stdout!r}"
    )
    assert "parse error" in out.stderr


def test_parser_works_without_pyyaml_in_env(tmp_path: Path) -> None:
    """Pin: the parser must succeed under a stripped python env.

    Simulates the portable-host case where global python3 lacks PyYAML.
    The parser is stdlib-only so it must not need anything beyond the
    interpreter.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text("worktree_scopes:\n  board: [src/board/, tests/board/]\n")
    out = subprocess.run(
        [
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            "PYTHONPATH=/dev/null",
            "python3",
            str(PARSER),
            str(cfg),
            "board",
        ],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout == "src/board/,tests/board/"


# --- hook integration tests ----------------------------------------------


def _run_hook(
    cwd: Path,
    file_path: Path | str,
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"cwd": str(cwd), "tool_input": {"file_path": str(file_path)}})
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
    )


def _make_worktree(tmp_path: Path, scope: str) -> tuple[Path, Path]:
    """Create a tiny git worktree-shaped tree with the given scope name.

    Returns (main_repo_root, worktree_path). The worktree's basename is
    `wt-<scope>` so the hook's scope-derivation logic resolves to `scope`.
    """
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True)
    # Seed an initial commit so worktree-add works.
    (main / "seed").write_text("seed\n")
    subprocess.run(["git", "-C", str(main), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "seed",
        ],
        check=True,
        capture_output=True,
    )
    wt_path = tmp_path / f"wt-{scope}"
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "worktree",
            "add",
            "-q",
            str(wt_path),
            "-b",
            f"wt-{scope}",
        ],
        check=True,
        capture_output=True,
    )
    return main, wt_path


def test_hook_allows_in_scope_path(tmp_path: Path) -> None:
    main, wt = _make_worktree(tmp_path, "board")
    (main / ".cloglog").mkdir()
    (main / ".cloglog/config.yaml").write_text(
        "worktree_scopes:\n  board: [src/board/, tests/board/]\n  agent: [src/agent/]\n"
    )
    target = wt / "src/board/models.py"
    out = _run_hook(wt, target)
    assert out.returncode == 0, f"hook blocked an in-scope write: stderr={out.stderr!r}"


def test_hook_blocks_out_of_scope_path(tmp_path: Path) -> None:
    main, wt = _make_worktree(tmp_path, "board")
    (main / ".cloglog").mkdir()
    (main / ".cloglog/config.yaml").write_text(
        "worktree_scopes:\n  board: [src/board/, tests/board/]\n  agent: [src/agent/]\n"
    )
    target = wt / "src/agent/services.py"
    out = _run_hook(wt, target)
    assert out.returncode == 2, (
        f"hook should have blocked an agent-scope write from a board worktree, "
        f"got rc={out.returncode} stderr={out.stderr!r}"
    )
    assert "Blocked" in out.stderr
    assert "src/agent/services.py" in out.stderr


def test_hook_works_when_global_pyyaml_is_unavailable(tmp_path: Path) -> None:
    """End-to-end pin: the hook + parser combination still enforces scope
    when the surrounding python environment cannot `import yaml`.

    This is the failure mode docs/invariants.md:76 names — the previous
    implementation silently allowed every write on hosts without PyYAML.
    """
    main, wt = _make_worktree(tmp_path, "board")
    (main / ".cloglog").mkdir()
    (main / ".cloglog/config.yaml").write_text(
        "worktree_scopes:\n  board: [src/board/]\n  agent: [src/agent/]\n"
    )
    payload = json.dumps(
        {
            "cwd": str(wt),
            "tool_input": {"file_path": str(wt / "src/agent/services.py")},
        }
    )
    out = subprocess.run(
        [
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            "PYTHONPATH=/dev/null",
            "HOME=" + str(tmp_path),
            "bash",
            str(HOOK),
        ],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 2, (
        f"hook must still enforce scope without PyYAML, got rc={out.returncode} "
        f"stdout={out.stdout!r} stderr={out.stderr!r}"
    )
    assert "Blocked" in out.stderr


def test_hook_fails_closed_on_malformed_config(tmp_path: Path) -> None:
    """Codex-flagged regression pin (PR #239 review): a malformed
    ``worktree_scopes`` block must BLOCK writes, not silently allow them.

    The previous ``import yaml`` snippet swallowed ImportError into
    allow-all, and the first cut of this hook preserved the same
    fallthrough by writing ``ALLOWED=$(... ) || exit 0`` after the
    parser invocation. That left the silent-bypass exactly where it
    was — any mid-edit / merge-conflict-marker config turned the hook
    into a no-op for every worktree. Pin: malformed config => exit 2.
    """
    main, wt = _make_worktree(tmp_path, "board")
    (main / ".cloglog").mkdir()
    # Missing closing bracket on the flow list — parser exits 4 with
    # ``parse error`` on stderr.
    (main / ".cloglog/config.yaml").write_text(
        "worktree_scopes:\n  board: [src/board/, tests/board/\n"
    )
    out = _run_hook(wt, wt / "src/agent/services.py")
    assert out.returncode == 2, (
        f"hook must fail closed on malformed worktree_scopes, got rc={out.returncode} "
        f"stdout={out.stdout!r} stderr={out.stderr!r}"
    )
    assert "Blocked: failed to parse worktree_scopes" in out.stderr
    # The parser's own stderr must be propagated so an operator can fix the config.
    assert "parse error" in out.stderr
