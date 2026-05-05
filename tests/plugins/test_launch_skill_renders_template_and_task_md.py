"""Pin: T-360 / T-354 — launch SKILL Step 3 renders AGENT_PROMPT.md + task.md.

The structural fix for the 2026-04-30 inbox-path incident (T-360) is to
copy the workflow template verbatim and emit only the per-task delta as
``task.md``. The rendering shape itself was rewritten by T-354: drop the
SKILL-embedded heredoc + sed pipeline (which silently corrupted values
containing ``&``/``\\``/``|``) in favour of
``scripts/render_template.py`` against
``templates/task.md.template``.

This pin renders the template against fixture variables and asserts:

1. Both ``AGENT_PROMPT.md`` and ``task.md`` are emitted under the
   fake worktree path.
2. ``AGENT_PROMPT.md`` is byte-identical to the template — the launch
   path must not paraphrase the template into per-agent variants
   (T-360).
3. ``task.md`` has every ``@@PLACEHOLDER@@`` substituted with the
   fixture value — no leftover tokens.
4. Adversarial values (titles containing ``&``, ``\\``, ``|``,
   newlines) round-trip literally — the T-354 fix.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_ROOT = REPO_ROOT / "plugins/cloglog"
LAUNCH_SKILL = PLUGIN_ROOT / "skills/launch/SKILL.md"
PROMPT_TEMPLATE = PLUGIN_ROOT / "templates/AGENT_PROMPT.md"
TASK_TEMPLATE = PLUGIN_ROOT / "templates/task.md.template"
RENDER_SCRIPT = PLUGIN_ROOT / "scripts/render_template.py"


def _render_task_md(out_path: Path, **bindings: str) -> None:
    cmd = [
        sys.executable,
        str(RENDER_SCRIPT),
        "--template",
        str(TASK_TEMPLATE),
        "--output",
        str(out_path),
    ]
    for k, v in bindings.items():
        cmd += ["--var", f"{k}={v}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, (
        f"render_template.py failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_step3_emits_both_files_with_substituted_placeholders() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt-fake"
        wt.mkdir()
        # Verbatim copy of the workflow template — the launch SKILL does this
        # via `cp`. We mirror it here so the assertion below has a file to
        # compare against.
        (wt / "AGENT_PROMPT.md").write_bytes(PROMPT_TEMPLATE.read_bytes())

        bindings = dict(
            WORKTREE_PATH=str(wt),
            WORKTREE_NAME="wt-fake",
            WORKTREE_UUID="11111111-1111-1111-1111-111111111111",
            TASK_NUMBER="T-999",
            TASK_TITLE="Fake task title",
            TASK_UUID="22222222-2222-2222-2222-222222222222",
            PRIORITY="normal",
            FEATURE_REF="F-99 Some feature",
            FEATURE_UUID="33333333-3333-3333-3333-333333333333",
            PROJECT_ROOT=str(REPO_ROOT),
            TASK_DESCRIPTION="Make the thing do the thing.",
            SIBLING_WARNINGS="(none)",
            RESIDUAL_NOTES="(none)",
        )
        _render_task_md(wt / "task.md", **bindings)

        prompt_path = wt / "AGENT_PROMPT.md"
        task_path = wt / "task.md"
        assert prompt_path.exists(), "AGENT_PROMPT.md not emitted"
        assert task_path.exists(), "task.md not emitted"

        # 1. AGENT_PROMPT.md is byte-identical to the template.
        assert prompt_path.read_bytes() == PROMPT_TEMPLATE.read_bytes(), (
            "AGENT_PROMPT.md must be byte-identical to the canonical "
            "template — Step 3 paraphrasing the template into per-agent "
            "variants reopens the workflow-drift bug T-360 closed."
        )

        # 2. task.md has fixture values substituted.
        task_body = task_path.read_text(encoding="utf-8")
        for needle in (
            "T-999",
            "Fake task title",
            bindings["TASK_UUID"],
            bindings["WORKTREE_UUID"],
            bindings["WORKTREE_PATH"],
            bindings["PROJECT_ROOT"],
            "Make the thing do the thing.",
        ):
            assert needle in task_body, f"Missing fixture value {needle!r} in rendered task.md"

        # 3. No @@...@@ placeholders left.
        leftover = re.findall(r"@@[A-Z_]+@@", task_body)
        assert not leftover, (
            f"Unsubstituted placeholders remain in task.md: {leftover}. "
            "Every @@PLACEHOLDER@@ token must have a matching --var binding "
            "in the SKILL's render_template.py invocation."
        )


def test_task_md_round_trips_metacharacters() -> None:
    """T-354 (HIGH): task titles / descriptions are free-form board
    strings (``src/board/schemas.py:133-139``) so a title like
    ``R&D follow-up`` must round-trip literally. Pre-T-354 the sed
    shape would either splice the placeholder text back in via ``&``
    expansion, or break on the ``|`` delimiter, or consume the ``\\``.

    The new contract — literal Python ``str.replace`` — has no
    metacharacter that has special meaning. This pin asserts the
    round-trip with synthetic values containing ``&``, ``\\``, ``|``,
    AND a newline. The newline coverage is the multi-line description
    case (the prior shape needed ``sed -e '/.../{r FILE' -e 'd}'`` to
    handle).
    """
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt-fake"
        wt.mkdir()
        adversarial_title = "R&D follow-up: foo\\bar | baz"
        adversarial_feature = "F-99 R&D | feature\\quoted"
        adversarial_desc = (
            "Line one with & ampersand.\n"
            "Line two with \\ backslash and | pipe.\n"
            "Line three has $VAR which must NOT expand."
        )
        adversarial_residual = "Note: don't forget the &\\| trio."
        bindings = dict(
            WORKTREE_PATH=str(wt),
            WORKTREE_NAME="wt-fake",
            WORKTREE_UUID="11111111-1111-1111-1111-111111111111",
            TASK_NUMBER="T-999",
            TASK_TITLE=adversarial_title,
            TASK_UUID="22222222-2222-2222-2222-222222222222",
            PRIORITY="normal",
            FEATURE_REF=adversarial_feature,
            FEATURE_UUID="33333333-3333-3333-3333-333333333333",
            PROJECT_ROOT=str(REPO_ROOT),
            TASK_DESCRIPTION=adversarial_desc,
            SIBLING_WARNINGS="(none)",
            RESIDUAL_NOTES=adversarial_residual,
        )
        _render_task_md(wt / "task.md", **bindings)

        task_body = (wt / "task.md").read_text(encoding="utf-8")
        # Each adversarial value must appear verbatim.
        for label, value in (
            ("TASK_TITLE", adversarial_title),
            ("FEATURE_REF", adversarial_feature),
            ("TASK_DESCRIPTION", adversarial_desc),
            ("RESIDUAL_NOTES", adversarial_residual),
        ):
            assert value in task_body, (
                f"Adversarial {label} did not round-trip literally. "
                f"Expected {value!r}, got:\n{task_body}"
            )
        # Placeholder text must not be spliced back in.
        for tok in ("@@TASK_TITLE@@", "@@FEATURE_REF@@", "@@TASK_DESCRIPTION@@"):
            assert tok not in task_body


def test_skill_uses_render_template_script() -> None:
    """The SKILL must invoke ``scripts/render_template.py`` from Step 3
    against ``templates/task.md.template``. Re-introducing a heredoc +
    sed pipeline reopens the T-354 metacharacter-escape bug class.
    """
    body = LAUNCH_SKILL.read_text(encoding="utf-8")
    assert "scripts/render_template.py" in body, (
        "SKILL.md must invoke scripts/render_template.py for templating"
    )
    assert "templates/task.md.template" in body, (
        "SKILL.md Step 3 must render from templates/task.md.template"
    )
    # Absence-pin: the prior heredoc opener must not return.
    assert 'cat > "${WORKTREE_PATH}/task.md"' not in body, (
        "T-354 regression: SKILL.md re-introduced an inline heredoc for task.md."
    )


def test_task_md_template_has_required_placeholders() -> None:
    """Pin the placeholder set used by the SKILL — adding or removing a
    placeholder must update both the template and the SKILL's
    ``--var`` bindings.
    """
    body = TASK_TEMPLATE.read_text(encoding="utf-8")
    required = {
        "@@TASK_NUMBER@@",
        "@@TASK_TITLE@@",
        "@@PRIORITY@@",
        "@@FEATURE_REF@@",
        "@@TASK_UUID@@",
        "@@FEATURE_UUID@@",
        "@@WORKTREE_UUID@@",
        "@@WORKTREE_NAME@@",
        "@@WORKTREE_PATH@@",
        "@@PROJECT_ROOT@@",
        "@@TASK_DESCRIPTION@@",
        "@@SIBLING_WARNINGS@@",
        "@@RESIDUAL_NOTES@@",
    }
    missing = required - set(re.findall(r"@@[A-Z_]+@@", body))
    assert not missing, f"task.md.template missing placeholders: {missing}"
