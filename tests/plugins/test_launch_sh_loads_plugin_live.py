"""T-387 pin: launch.sh launches claude with `--plugin-dir` pointing at the
worktree's own `plugins/cloglog/` so plugin edits take effect on the next
agent launch.

Without `--plugin-dir`, claude resolves the cloglog plugin from its
install-time cache (`claude plugins install`). Edits to
`plugins/cloglog/skills/**`, `hooks/**`, or `templates/**` are then
silently invisible to agents launched after the edit — the cache freezes
the plugin contents at install time.

Post-T-354 the launch.sh is rendered from
``templates/launch.sh.template`` via ``scripts/render_template.py``,
so this pin reads the template directly rather than re-extracting a
heredoc body from SKILL.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins/cloglog"
SKILL_PATH = PLUGIN_ROOT / "skills/launch/SKILL.md"
TEMPLATE_PATH = PLUGIN_ROOT / "templates/launch.sh.template"
RENDER_SCRIPT = PLUGIN_ROOT / "scripts/render_template.py"


def _render(tmp_path: Path) -> str:
    wt = tmp_path / "wt-foo"
    proj = tmp_path / "proj"
    (wt / ".cloglog").mkdir(parents=True)
    (wt / "plugins" / "cloglog").mkdir(parents=True)
    proj.mkdir(parents=True)
    out = wt / ".cloglog" / "launch.sh"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--template",
            str(TEMPLATE_PATH),
            "--output",
            str(out),
            "--var",
            f"WORKTREE_PATH={wt}",
            "--var",
            f"PROJECT_ROOT={proj}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return out.read_text()


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


def test_template_documents_plugin_dir_rationale() -> None:
    """The prose anchor moved from the SKILL heredoc to the
    ``docs/launch-design.md`` history. Pin the T-387 reference there so
    a future edit that drops ``--plugin-dir`` from the template leaves a
    breadcrumb for the next reader.
    """
    template_body = TEMPLATE_PATH.read_text()
    assert "--plugin-dir" in template_body, "launch.sh.template must reference --plugin-dir"
    design_doc = PLUGIN_ROOT / "docs/launch-design.md"
    assert design_doc.is_file(), f"{design_doc} missing — T-354 design doc"
    design_body = design_doc.read_text()
    assert "T-387" in design_body, (
        "docs/launch-design.md must reference T-387 so the plugin "
        "live-load rationale survives future edits."
    )
