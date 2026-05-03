"""T-387 pin: launch.sh launches claude with `--plugin-dir` pointing at the
worktree's own `plugins/cloglog/` so plugin edits take effect on the next
agent launch.

Without `--plugin-dir`, claude resolves the cloglog plugin from its
install-time cache (`claude plugins install`). Edits to
`plugins/cloglog/skills/**`, `hooks/**`, or `templates/**` are then
silently invisible to agents launched after the edit — the cache freezes
the plugin contents at install time. This pin asserts that the rendered
launch.sh:

  - declares a `--plugin-dir` flag in the claude invocation, AND
  - the flag's path is anchored on `$WORKTREE_PATH/plugins/cloglog`
    (the worktree-local plugin source, not a shared install).

A regression that drops the flag, or hardcodes a single shared path
(e.g. `~/.claude/plugins/...`), reopens the install-time-cache trap.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"

HEREDOC_OPEN = "cat > \"${WORKTREE_PATH}/.cloglog/launch.sh\" << 'EOF'"


def _extract_emit_block(skill_text: str) -> str:
    lines = skill_text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == HEREDOC_OPEN)
    eof = next(j for j in range(start + 1, len(lines)) if lines[j].strip() == "EOF")
    post: list[str] = []
    for k in range(eof + 1, len(lines)):
        if lines[k].strip().startswith("chmod +x"):
            break
        post.append(lines[k])
    return "\n".join(lines[start : eof + 1] + post) + "\n"


def _render(tmp_path: Path) -> str:
    skill = SKILL_PATH.read_text()
    block = _extract_emit_block(skill)
    wt = tmp_path / "wt-foo"
    proj = tmp_path / "proj"
    (wt / ".cloglog").mkdir(parents=True)
    (wt / "plugins" / "cloglog").mkdir(parents=True)
    proj.mkdir(parents=True)
    result = subprocess.run(
        ["bash", "-c", block],
        env={
            "PATH": "/usr/bin:/bin",
            "WORKTREE_PATH": str(wt),
            "PROJECT_ROOT": str(proj),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return (wt / ".cloglog" / "launch.sh").read_text()


def test_rendered_launch_sh_passes_plugin_dir_flag(tmp_path: Path) -> None:
    rendered = _render(tmp_path)
    assert "--plugin-dir" in rendered, (
        "T-387 regression: rendered launch.sh must pass `--plugin-dir` to "
        "claude so the cloglog plugin loads live from the worktree's "
        "on-disk source. Without it, claude reads from the install-time "
        "cache and plugin edits are invisible to the agent."
    )


def test_plugin_dir_flag_anchors_on_worktree_path(tmp_path: Path) -> None:
    rendered = _render(tmp_path)
    # The path must be derived from $WORKTREE_PATH so each worktree picks
    # up edits to its own plugin copy, not a shared install.
    pattern = re.compile(
        r"--plugin-dir\s+\$?\{?WORKTREE_PATH\}?/plugins/cloglog\b"
        r'|--plugin-dir\s+"?[^\s"]*/plugins/cloglog\b'
    )
    assert pattern.search(rendered), (
        "T-387: --plugin-dir path must resolve to "
        "$WORKTREE_PATH/plugins/cloglog (the worktree-local plugin "
        "source). Hardcoding a global install path (e.g. "
        "~/.claude/plugins/...) reopens the install-time freeze."
    )


def test_skill_documents_plugin_dir_rationale() -> None:
    """The prose must explain *why* — a future edit that drops the flag
    leaves the next reader no way to rediscover the install-time-cache
    failure mode."""
    body = SKILL_PATH.read_text()
    assert "--plugin-dir" in body, "launch SKILL.md must mention --plugin-dir"
    assert "T-387" in body, (
        "launch SKILL.md must reference T-387 so the plugin live-load "
        "rationale survives future edits."
    )
