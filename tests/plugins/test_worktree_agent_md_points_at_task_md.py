"""Pin: T-360 (codex round 3 CRITICAL) — worktree-agent.md must point at
task.md for the per-task delta.

Before T-360 the prompt template embedded both workflow rules and the
per-task assignment, so `plugins/cloglog/agents/worktree-agent.md` could
truthfully say "AGENT_PROMPT.md contains your feature assignment and
task IDs." T-360 split those concerns: AGENT_PROMPT.md is the static
workflow template (copied verbatim into every worktree), and `task.md`
is the per-task delta (task UUID / feature UUID / worktree IDs / paths
/ description / sibling warnings / residual TODOs hint / optional
workflow_override).

If `worktree-agent.md` keeps describing the old contract, a relaunched
session that follows it literally will read `AGENT_PROMPT.md` for the
current task assignment — but `AGENT_PROMPT.md` is the static template
that does not change between tasks on the same worktree, so the agent
would silently work on the wrong task. This pin asserts the agent
definition points at `task.md` for the per-task fields.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKTREE_AGENT = REPO_ROOT / "plugins/cloglog/agents/worktree-agent.md"


def test_worktree_agent_md_points_at_task_md_for_per_task_fields() -> None:
    body = WORKTREE_AGENT.read_text(encoding="utf-8")
    assert "task.md" in body, (
        "worktree-agent.md must reference task.md as the per-task delta "
        "source — T-360 moved task IDs / paths / description / "
        "workflow_override out of AGENT_PROMPT.md and into task.md. "
        "Without this pointer, a relaunched session can read the static "
        "template and miss that the active task changed."
    )


def test_worktree_agent_md_describes_agent_prompt_as_workflow_template() -> None:
    """Phrasing pin: the file must call AGENT_PROMPT.md the *workflow
    template*, not the *task assignment* file. The exact phrase
    "workflow template" is the simplest stable anchor — paraphrase
    drift won't accidentally satisfy it.
    """
    body = WORKTREE_AGENT.read_text(encoding="utf-8")
    assert "workflow template" in body, (
        "worktree-agent.md must describe AGENT_PROMPT.md as the "
        "workflow template (T-360). The earlier wording 'it contains "
        "your feature assignment and task IDs' is the antipattern."
    )
