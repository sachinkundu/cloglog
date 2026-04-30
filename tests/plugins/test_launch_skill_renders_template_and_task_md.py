"""Pin: T-360 — launch SKILL Step 3 renders template + task.md.

The structural fix for the 2026-04-30 inbox-path incident is to copy the
workflow template verbatim and emit only the per-task delta as
``task.md``. This test extracts Step 3 from the SKILL, runs the relevant
bash against fixture variables, and asserts:

1. Both ``AGENT_PROMPT.md`` and ``task.md`` are emitted under the
   fake worktree path.
2. ``AGENT_PROMPT.md`` is byte-identical to the template — the launch
   path must not paraphrase the template into per-agent variants.
3. ``task.md`` has every ``@@PLACEHOLDER@@`` substituted with the
   fixture value — no leftover tokens.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"
TEMPLATE = REPO_ROOT / "plugins/cloglog/templates/AGENT_PROMPT.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing"
    return p.read_text(encoding="utf-8")


def _extract_step3_bash() -> str:
    """Pull the first ```bash``` block under '## Step 3'."""
    body = _read(LAUNCH_SKILL)
    section = re.search(
        r"## Step 3:.*?(?=\n## Step 4|\n## Pipeline|\Z)",
        body,
        flags=re.DOTALL,
    )
    assert section, "Step 3 section missing or its heading was renamed"
    blocks = re.findall(r"```bash\n(.*?)\n```", section.group(0), flags=re.DOTALL)
    assert blocks, "Step 3 must contain at least one ```bash``` code block"
    # The first bash block is the one that does the cp + heredoc + sed.
    return blocks[0]


def test_step3_emits_both_files_with_substituted_placeholders() -> None:
    bash = _extract_step3_bash()

    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt-fake"
        wt.mkdir()
        env = {
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "plugins/cloglog"),
            "WORKTREE_PATH": str(wt),
            "WORKTREE_NAME": "wt-fake",
            "WORKTREE_UUID": "11111111-1111-1111-1111-111111111111",
            "TASK_NUMBER": "T-999",
            "TASK_TITLE": "Fake task title",
            "TASK_UUID": "22222222-2222-2222-2222-222222222222",
            "PRIORITY": "normal",
            "FEATURE_REF": "F-99 Some feature",
            "FEATURE_UUID": "33333333-3333-3333-3333-333333333333",
            "PROJECT_ROOT": str(REPO_ROOT),
            # Multi-line vars — the SKILL prose says these come via temp
            # files; for the pin we drop them in via env so the simple
            # `sed -e` substitutions work. Single-line is sufficient to
            # prove the rendering shape.
            "TASK_DESCRIPTION": "Make the thing do the thing.",
            "SIBLING_WARNINGS": "(none)",
            "RESIDUAL_NOTES": "(none)",
        }

        # Codex round 3: the test now executes the documented Step 3
        # block AS-IS — no per-test `bash_full` augmentation. Any
        # placeholder Step 3 forgets to substitute will leave a leftover
        # @@TOKEN@@ token, which the no-leftover assertion below catches.
        bash_full = bash

        result = subprocess.run(
            ["bash", "-c", bash_full],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Step 3 bash failed: rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        prompt_path = wt / "AGENT_PROMPT.md"
        task_path = wt / "task.md"
        assert prompt_path.exists(), "AGENT_PROMPT.md not emitted"
        assert task_path.exists(), "task.md not emitted"

        # 1. AGENT_PROMPT.md is byte-identical to the template.
        assert prompt_path.read_bytes() == TEMPLATE.read_bytes(), (
            "AGENT_PROMPT.md must be byte-identical to the canonical "
            "template — Step 3 paraphrasing the template into per-agent "
            "variants reopens the workflow-drift bug T-360 closed."
        )

        # 2. task.md has fixture values substituted.
        task_body = task_path.read_text(encoding="utf-8")
        assert "T-999" in task_body
        assert "Fake task title" in task_body
        assert env["TASK_UUID"] in task_body
        assert env["WORKTREE_UUID"] in task_body
        assert env["WORKTREE_PATH"] in task_body
        assert env["PROJECT_ROOT"] in task_body
        assert "Make the thing do the thing." in task_body

        # 3. No @@...@@ placeholders left (every token substituted).
        leftover = re.findall(r"@@[A-Z_]+@@", task_body)
        assert not leftover, (
            f"Unsubstituted placeholders remain in task.md: {leftover}. "
            "Every @@PLACEHOLDER@@ token must have a matching sed "
            "substitution in Step 3 or the per-task delta will leak as "
            "raw tokens into the agent's view."
        )


def test_step3_escapes_sed_replacement_metacharacters() -> None:
    """Codex round 2 (HIGH): task titles / descriptions are free-form
    board strings (`src/board/schemas.py:133-139`) so a title like
    ``R&D follow-up`` must round-trip literally. Without escaping, sed
    expands ``&`` to the matched pattern and ``\\`` to an escape, and
    `R&D` would render as ``R@@TASK_TITLE@@D follow-up`` (the
    placeholder text spliced back in via `&`).

    Pin the round-trip with a synthetic title containing all three
    replacement metacharacters: ``&``, ``\\``, and the chosen ``|``
    delimiter.
    """
    bash = _extract_step3_bash()
    assert "_sed_escape_replacement" in bash, (
        "Step 3 must define a `_sed_escape_replacement` helper that "
        "escapes & / \\ / | before the sed -i pass — free-form board "
        "metadata otherwise corrupts the rendered task.md."
    )

    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt-fake"
        wt.mkdir()
        env = {
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "plugins/cloglog"),
            "WORKTREE_PATH": str(wt),
            "WORKTREE_NAME": "wt-fake",
            "WORKTREE_UUID": "11111111-1111-1111-1111-111111111111",
            "TASK_NUMBER": "T-999",
            # Adversarial title: ampersand, backslash, AND the sed delimiter.
            "TASK_TITLE": "R&D follow-up: foo\\bar | baz",
            "TASK_UUID": "22222222-2222-2222-2222-222222222222",
            "PRIORITY": "normal",
            "FEATURE_REF": "F-99 R&D feature",
            "FEATURE_UUID": "33333333-3333-3333-3333-333333333333",
            "PROJECT_ROOT": str(REPO_ROOT),
            "TASK_DESCRIPTION": "Description with & and \\ chars.",
            "SIBLING_WARNINGS": "(none)",
            "RESIDUAL_NOTES": "(none)",
        }

        # Run the documented Step 3 block as-is (codex round 3).
        bash_full = bash

        result = subprocess.run(
            ["bash", "-c", bash_full],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Step 3 bash failed: rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )

        task_body = (wt / "task.md").read_text(encoding="utf-8")
        # Each adversarial value must appear verbatim — no `&` expansion,
        # no `\` consumed, no `|`-delimiter break.
        assert env["TASK_TITLE"] in task_body, (
            f"Adversarial title {env['TASK_TITLE']!r} did not round-trip "
            "literally into task.md. Rendered:\n" + task_body
        )
        assert env["FEATURE_REF"] in task_body, (
            f"Adversarial FEATURE_REF {env['FEATURE_REF']!r} did not round-trip literally."
        )
        assert env["TASK_DESCRIPTION"] in task_body, (
            "Adversarial TASK_DESCRIPTION did not round-trip literally."
        )
        # Negative pin — placeholder text must not be spliced back in.
        assert "@@TASK_TITLE@@" not in task_body
        assert "@@FEATURE_REF@@" not in task_body


def test_step3_uses_quoted_heredoc_for_task_md() -> None:
    """Quoted heredoc (``<< 'TASK_EOF'``) keeps ``${VAR}`` literal in
    ``task.md`` — only the explicit ``@@PLACEHOLDER@@`` sed pass
    substitutes values. Mirrors T-353's quoted-heredoc discipline for
    launch.sh.
    """
    bash = _extract_step3_bash()
    assert "<< 'TASK_EOF'" in bash, (
        "Step 3 must emit task.md via a quoted heredoc (<< 'TASK_EOF') "
        "so ${VAR} references in the body stay literal. An unquoted "
        "heredoc would expand any leaked shell var at write time and "
        "could leak operator state into the agent's task.md."
    )
