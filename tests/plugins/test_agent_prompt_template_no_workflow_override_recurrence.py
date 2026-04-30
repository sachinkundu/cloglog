"""Pin: T-360 — workflow_override is a field, not a forked template.

The override mechanism for rare deviations from the standard `pr_merged`
flow is a single field on ``task.md`` (`workflow_override: <value>`),
which the template branches on internally. The antipattern this pin
guards against is the opposite of T-360's structural fix: re-inlining
per-flag if/else trees back into the template, growing it into the same
"one big file with N copies of the workflow" shape that hand-pasted
prompts had.

CLAUDE.md learning **"Absence-pins on antipattern substrings collide
with documentation that names the antipattern"** applies — the template
must still describe the override field in prose. This pin checks
**executable shape**, not text mentions:

- Count occurrences of ``workflow_override:`` (the YAML key form, which
  appears in prose / task.md examples).
- Cap the count at a small budget — the template defines the override
  field once and references the YAML key form in at most a couple of
  places (definition + example). Three or more occurrences signals the
  template is starting to grow per-flag branches.

If a future maintainer adds a third ``workflow_override`` value
(``no_demo``, ``prototype``, etc.) by inlining a new branch in the
template, that's the cue to fold the variants out into named template
files (`AGENT_PROMPT_skip_pr.md`, etc.) instead of branching this
template further. The Residual TODOs hint in T-360's task.md says this
explicitly — the pin enforces the discipline.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = REPO_ROOT / "plugins/cloglog/templates/AGENT_PROMPT.md"

# Budget: definition + at most one prose reference. Three or more is the
# regression signal.
MAX_WORKFLOW_OVERRIDE_OCCURRENCES = 2


def test_template_does_not_inline_per_flag_override_branches() -> None:
    body = TEMPLATE.read_text(encoding="utf-8")
    count = body.count("workflow_override:")
    assert count <= MAX_WORKFLOW_OVERRIDE_OCCURRENCES, (
        f"Template references the YAML form 'workflow_override:' {count} "
        f"times — budget is {MAX_WORKFLOW_OVERRIDE_OCCURRENCES}. Going "
        "above signals the template is starting to inline a branch per "
        "override value. Fold the variants out into named template "
        "files (AGENT_PROMPT_skip_pr.md, etc.) instead. See T-360 "
        "Residual TODOs hint."
    )


def test_template_defines_skip_pr_override_value() -> None:
    """Positive pin: the only override value defined today is ``skip_pr``.

    Counterpart to the absence-pin above — ensures the override
    mechanism actually exists. If a future edit removes it entirely the
    template silently regresses to "no way to deviate from pr_merged",
    which the worktree-agent.md plan-task flow depends on.
    """
    body = TEMPLATE.read_text(encoding="utf-8")
    assert "skip_pr" in body, (
        "Template must define the `skip_pr` workflow override — it's "
        "the documented escape hatch for docs/research/prototype tasks "
        "that don't open a PR. Removing it breaks the plan-task and "
        "no-PR-task shutdown sequences."
    )
