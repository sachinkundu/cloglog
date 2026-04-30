"""T-353 pin: launch SKILL emits a syntactically clean launch.sh.

Prior bug (observed in antisocial 2026-04-30): the SKILL used an *unquoted*
heredoc with `\\$1` / `\\$2` escapes for helper-function positional args. When
the SKILL block was relayed through the LLM-agent Bash-tool → bash boundary,
the `\\$N` escapes collapsed inconsistently, producing rendered files like
`local file="\\"; local key="\\"` and tripping
`unexpected EOF while looking for matching '"'` at exec time.

This pin reads the SKILL, materialises the launch.sh-emitting block against
fixture paths, and asserts that:
  - The rendered file passes `bash -n` (syntactically valid).
  - The exact helper-arg lines that broke in antisocial are present.
  - The two operator-host paths got substituted in via `sed`.
  - No `\\$` antipattern remains in the rendered file.
  - No unsubstituted `@@...@@` placeholders remain.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"

HEREDOC_OPEN = "cat > \"${WORKTREE_PATH}/.cloglog/launch.sh\" << 'EOF'"


def _extract_emit_block(skill_text: str) -> str:
    """Extract the bash that emits launch.sh: from `cat > ... << 'EOF'`
    through both `sed -i` substitution lines (stopping before `chmod +x`)."""
    lines = skill_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == HEREDOC_OPEN:
            start = i
            break
    assert start is not None, (
        f"Could not find quoted-heredoc opener {HEREDOC_OPEN!r} in {SKILL_PATH}. "
        "T-353 requires `<< 'EOF'` (single-quoted delimiter)."
    )
    # Find the closing EOF line (must be the literal `EOF` on its own).
    eof = None
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == "EOF":
            eof = j
            break
    assert eof is not None, "No closing EOF for the launch.sh heredoc"
    # Then collect every line between EOF and `chmod +x` — this captures the
    # `sed -i` substitution pair and any setup lines (e.g. the
    # `_sed_escape_replacement` helper added in T-353 codex round 1) that
    # must run before them. Skip blank lines and pure-comment lines so we
    # don't trip on Markdown prose mixed in (we are inside a fenced bash
    # block so that's unlikely, but be defensive).
    post_lines: list[str] = []
    found_chmod = False
    sed_count = 0
    for k in range(eof + 1, len(lines)):
        stripped = lines[k].strip()
        if stripped.startswith("chmod +x"):
            found_chmod = True
            break
        post_lines.append(lines[k])
        if stripped.startswith("sed -i"):
            sed_count += 1
    assert found_chmod, "No `chmod +x` line found after the launch.sh heredoc"
    assert sed_count == 2, (
        f"Expected 2 `sed -i` substitution lines after the heredoc; got {sed_count}"
    )
    block_lines = lines[start : eof + 1] + post_lines
    return "\n".join(block_lines) + "\n"


def test_launch_sh_renders_clean(tmp_path: Path) -> None:
    skill_text = SKILL_PATH.read_text()
    emit_block = _extract_emit_block(skill_text)

    # T-353 codex round 1: include `&` in both fixture paths so the sed
    # replacement-string escape is exercised. In a sed replacement, `&`
    # expands to the matched text; without the `s/[&|\]/\\&/g` escape,
    # the rendered file would contain `fake@@WORKTREE_PATH@@wt` instead of
    # `fake&wt`. Real-world trigger: a checkout under `~/R&D/`.
    wt_path = tmp_path / "fake&wt" / "foo"
    proj_root = tmp_path / "fake&proj"
    (wt_path / ".cloglog").mkdir(parents=True)
    proj_root.mkdir(parents=True)

    # Run the extracted block under bash with the fixture paths.
    result = subprocess.run(
        ["bash", "-c", emit_block],
        env={
            "PATH": "/usr/bin:/bin",
            "WORKTREE_PATH": str(wt_path),
            "PROJECT_ROOT": str(proj_root),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Emit block failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    rendered = (wt_path / ".cloglog" / "launch.sh").read_text()

    # 1. Syntactically valid bash.
    syntax_check = subprocess.run(
        ["bash", "-n", str(wt_path / ".cloglog" / "launch.sh")],
        capture_output=True,
        text=True,
    )
    assert syntax_check.returncode == 0, (
        f"`bash -n` failed on rendered launch.sh: {syntax_check.stderr!r}"
    )

    # 2. The exact helper-arg lines that broke in antisocial must be present.
    assert 'local file="$1"; local key="$2"' in rendered, (
        "T-353 regression: `_read_scalar_yaml` lost its $1/$2 references"
    )
    assert 'local sig="$1"' in rendered, "T-353 regression: `_on_signal` lost its $1 reference"
    assert 'local sig="${1:-unknown}"' in rendered, (
        "T-353 regression: `_unregister_fallback` lost its ${1:-unknown} reference"
    )

    # 3. Operator-host paths were substituted in.
    assert f'WORKTREE_PATH="{wt_path}"' in rendered, (
        "sed substitution for WORKTREE_PATH did not land"
    )
    assert f'PROJECT_ROOT="{proj_root}"' in rendered, (
        "sed substitution for PROJECT_ROOT did not land"
    )

    # 4. The pre-T-353 antipattern (`\$` inside a heredoc) must not appear in
    # the rendered output. A quoted heredoc emits `$` literally; any `\$` byte
    # in the rendered file means the SKILL slipped back to the unquoted form.
    assert "\\$" not in rendered, (
        "T-353 regression: rendered launch.sh contains the `\\$` antipattern. "
        "The launch SKILL heredoc must be quoted (`<< 'EOF'`)."
    )

    # 5. No leftover placeholders.
    assert "@@WORKTREE_PATH@@" not in rendered, (
        "Unsubstituted @@WORKTREE_PATH@@ placeholder remains"
    )
    assert "@@PROJECT_ROOT@@" not in rendered, "Unsubstituted @@PROJECT_ROOT@@ placeholder remains"


def test_skill_uses_quoted_heredoc() -> None:
    """Direct text-level pin: SKILL.md must contain the quoted-EOF opener and
    must not contain the unquoted-EOF opener for the launch.sh emitter."""
    skill_text = SKILL_PATH.read_text()
    assert HEREDOC_OPEN in skill_text, f"SKILL.md must use quoted heredoc: {HEREDOC_OPEN!r}"
    unquoted_pattern = re.compile(r'cat > "\$\{WORKTREE_PATH\}/\.cloglog/launch\.sh" << EOF\b')
    assert not unquoted_pattern.search(skill_text), (
        "SKILL.md must not use the unquoted `<< EOF` form for launch.sh "
        "(T-353: collapses `\\$N` across the LLM-agent boundary)."
    )
