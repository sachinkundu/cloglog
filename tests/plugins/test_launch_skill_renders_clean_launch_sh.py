"""T-353/T-354 pin: launch SKILL renders a syntactically clean launch.sh.

Pre-T-354 the SKILL emitted ``launch.sh`` from a quoted heredoc (T-353
fixed an earlier ``\\$N`` escape bug) and then ran ``sed -i`` to bake
host paths in. The sed pass tripped on host paths containing replacement
metacharacters (``&`` ``\\`` ``|``), and the ``_sed_escape_replacement``
helper that mitigated it lost its ``$1`` reference on the LLM-agent →
bash boundary, silently producing empty escapes. Visible failure: every
supervisor-rendered ``launch.sh`` shipped with the fallback prompt
``Read /AGENT_PROMPT.md and begin.`` (literal ``/AGENT_PROMPT.md`` at
filesystem root because ``${WORKTREE_PATH}`` was substituted with empty
string).

T-354 dropped the heredoc + sed shape entirely. The template
``templates/launch.sh.template`` is now a tracked static file; the
SKILL invokes ``scripts/render_template.py`` against it with
``--var KEY=VALUE`` bindings. Replacement is a literal Python
``str.replace`` so ``&``/``\\``/``|``/newlines round-trip verbatim.

This pin renders the template against adversarial host paths and asserts:
  - The rendered file passes ``bash -n`` (syntactically valid).
  - The exact helper-arg lines that broke in antisocial 2026-04-30 are
    present.
  - The two operator-host paths got substituted in.
  - No unsubstituted ``@@...@@`` placeholders remain.
  - The ``\\$`` antipattern from the pre-T-353 unquoted-heredoc shape
    is absent.
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


def _render(tmp_path: Path, worktree_path: Path, project_root: Path) -> Path:
    out = worktree_path / ".cloglog" / "launch.sh"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--template",
            str(TEMPLATE_PATH),
            "--output",
            str(out),
            "--var",
            f"WORKTREE_PATH={worktree_path}",
            "--var",
            f"PROJECT_ROOT={project_root}",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"render_template.py failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return out


def test_launch_sh_renders_clean(tmp_path: Path) -> None:
    """Adversarial host paths (``&``, ``|``, ``\\``) must round-trip
    literally. Pre-T-354 the sed shape would have spliced placeholder
    text back in via ``&`` expansion or broken on the ``|`` delimiter.
    """
    wt_path = tmp_path / "fake&wt|odd\\dir" / "foo"
    proj_root = tmp_path / "fake&proj|p\\r"
    wt_path.mkdir(parents=True)
    proj_root.mkdir(parents=True)

    rendered_path = _render(tmp_path, wt_path, proj_root)
    rendered = rendered_path.read_text(encoding="utf-8")

    # 1. Syntactically valid bash.
    syntax_check = subprocess.run(
        ["bash", "-n", str(rendered_path)],
        capture_output=True,
        text=True,
    )
    assert syntax_check.returncode == 0, (
        f"`bash -n` failed on rendered launch.sh: {syntax_check.stderr!r}"
    )

    # 2. Helper-arg lines that broke in antisocial 2026-04-30 are present.
    assert 'local file="$1"; local key="$2"' in rendered, (
        "T-353 regression: `_read_scalar_yaml` lost its $1/$2 references"
    )
    assert 'local sig="$1"' in rendered, "T-353 regression: `_on_signal` lost its $1 reference"
    assert 'local sig="${1:-unknown}"' in rendered, (
        "T-353 regression: `_unregister_fallback` lost its ${1:-unknown} reference"
    )

    # 3. Operator-host paths substituted verbatim.
    assert f'WORKTREE_PATH="{wt_path}"' in rendered, (
        "WORKTREE_PATH placeholder did not round-trip literally"
    )
    assert f'PROJECT_ROOT="{proj_root}"' in rendered, (
        "PROJECT_ROOT placeholder did not round-trip literally"
    )
    # 3b. The fallback prompt's path must also be substituted — that's the
    # exact failure mode the T-354 bug produced (`/AGENT_PROMPT.md` at root).
    assert f"Read {wt_path}/AGENT_PROMPT.md and begin." in rendered, (
        "T-354 regression: fallback prompt's WORKTREE_PATH placeholder lost. "
        "Pre-fix this rendered as `Read /AGENT_PROMPT.md and begin.`"
    )

    # 4. The pre-T-353 antipattern must not appear.
    assert "\\$" not in rendered, (
        "T-353 regression: rendered launch.sh contains the `\\$` antipattern"
    )

    # 5. No leftover placeholders.
    leftover = re.findall(r"@@[A-Z_]+@@", rendered)
    assert not leftover, f"Unsubstituted placeholders remain: {leftover}"


def test_launch_sh_template_no_metacharacter_escape_dance() -> None:
    """The whole point of T-354: the SKILL must NOT contain a sed-based
    rendering pipeline for launch.sh. A regression that re-introduces
    `cat > .../launch.sh << 'EOF'` plus `sed -i` reopens the metacharacter-
    escape bug class.
    """
    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    assert 'cat > "${WORKTREE_PATH}/.cloglog/launch.sh"' not in skill_text, (
        "T-354 regression: SKILL.md re-introduced an inline heredoc for launch.sh. "
        "Render via scripts/render_template.py against templates/launch.sh.template instead."
    )
    assert "_sed_escape_replacement" not in skill_text, (
        "T-354 regression: SKILL.md re-introduced the sed-escape helper. "
        "render_template.py uses literal str.replace — no escape needed."
    )
    # The recipe must invoke the render script.
    assert "scripts/render_template.py" in skill_text, (
        "SKILL.md must invoke scripts/render_template.py — that is the "
        "single rendering contract for launch.sh and task.md."
    )


def test_launch_sh_template_is_tracked() -> None:
    """The template file must exist as a tracked static file under
    plugins/cloglog/templates/. Encoding it as bash heredoc lines inside
    the SKILL Markdown was the T-354 antipattern.
    """
    assert TEMPLATE_PATH.is_file(), (
        f"{TEMPLATE_PATH} missing — launch.sh.template must be tracked under "
        "plugins/cloglog/templates/"
    )
    body = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert body.startswith("#!/bin/bash"), "Template must begin with bash shebang"
    assert "@@WORKTREE_PATH@@" in body
    assert "@@PROJECT_ROOT@@" in body
