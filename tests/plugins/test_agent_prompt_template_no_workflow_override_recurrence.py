"""Pin: T-360 — `workflow_override` must NOT return as a stored field.

Codex round 4 (HIGH) flagged that the template originally referenced a
launch-time-stored `workflow_override` field on task.md that no MCP /
backend contract actually populated (`src/agent/schemas.py:60-65`
exposes `skip_pr` only at `update_task_status` time, not as task
metadata). The fix moved the `skip_pr` decision to a runtime check the
agent makes from its own diff at PR time.

This pin asserts the YAML form `workflow_override:` does not return as
a launch-time-stored field. The template may still reference the term
`workflow_override` in prose explaining *why* it doesn't exist, but the
YAML-key form (`workflow_override: <value>`) must stay zero — a
non-zero count signals someone is re-introducing the antipattern.

The `skip_pr` runtime path is also pinned positively, so the template
cannot silently lose the no-PR escape hatch entirely.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE = REPO_ROOT / "plugins/cloglog/templates/AGENT_PROMPT.md"


def test_template_does_not_reintroduce_workflow_override_yaml_field() -> None:
    """The YAML-key form ``workflow_override:`` must not appear — no
    launch-time-stored override field exists in the board / MCP
    contracts (codex round 4 HIGH).
    """
    body = TEMPLATE.read_text(encoding="utf-8")
    count = body.count("workflow_override:")
    assert count == 0, (
        "Template must NOT reintroduce a `workflow_override:` YAML field "
        "on task.md — the board / MCP contracts have no such field. The "
        "`skip_pr` decision is runtime, made by the agent from its own "
        "diff at PR time. Found "
        f"{count} occurrence(s) of the YAML form."
    )


def test_template_keeps_skip_pr_runtime_path() -> None:
    """Positive pin: the `skip_pr` no-PR escape hatch must remain
    documented — removing it breaks docs/research/prototype tasks that
    finish without a PR.
    """
    body = TEMPLATE.read_text(encoding="utf-8")
    assert "skip_pr" in body, (
        "Template must keep the `skip_pr` runtime path documented — "
        "it's the only way docs/research/prototype tasks complete "
        "without a PR. Removing it breaks the plan-task and "
        "no-PR-task shutdown sequences."
    )
