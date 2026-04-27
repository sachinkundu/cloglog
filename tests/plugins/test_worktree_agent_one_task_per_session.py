"""Pin tests: T-329 — worktree-agent one-task-per-session contract.

Agents now exit after each pr_merged event (per-task work log + unregister +
exit) rather than calling get_my_tasks and looping to the next task. These
absence/presence pins catch regressions that re-introduce the old multi-task
loop or that drop the bootstrap/handoff guidance.

Presence-pins assert load-bearing guidance is present.
Absence-pins assert the superseded pattern does not return.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKTREE_AGENT = REPO_ROOT / "plugins/cloglog/agents/worktree-agent.md"
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"
CLOSE_WAVE_SKILL = REPO_ROOT / "plugins/cloglog/skills/close-wave/SKILL.md"
SETUP_SKILL = REPO_ROOT / "plugins/cloglog/skills/setup/SKILL.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing — fix the path or the file was moved"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# worktree-agent.md — step 13 must NOT call get_my_tasks after pr_merged
# ---------------------------------------------------------------------------


def test_worktree_agent_impl_step13_no_get_my_tasks_after_pr_merged() -> None:
    """After pr_merged the agent must exit, not loop via get_my_tasks."""
    body = _read(WORKTREE_AGENT)

    # The old pattern: "get_my_tasks and start the next task"
    # We pin its absence to catch a revert.
    assert "get_my_tasks` and start the next task" not in body, (
        "worktree-agent.md step 13 must not instruct the agent to call "
        "get_my_tasks and start the next backlog task after pr_merged. "
        "Agents now exit after each pr_merged; the supervisor relaunches "
        "for subsequent tasks. A revert re-introduces the multi-task loop "
        "that caused context overflow on F-53 (T-314 hit ~80% at task 2)."
    )


def test_worktree_agent_step13_no_start_next_backlog_task() -> None:
    """The old 'start the next backlog task' phrasing must not appear in step 13."""
    body = _read(WORKTREE_AGENT)
    assert "start the next backlog task" not in body, (
        "worktree-agent.md must not contain 'start the next backlog task' — "
        "that phrasing was the old step-13 instruction to continue in the "
        "same session. Agents now exit after pr_merged."
    )


def test_worktree_agent_step13_has_unregister_and_exit() -> None:
    """After pr_merged the agent must unregister and exit."""
    body = _read(WORKTREE_AGENT)
    assert "unregister_agent`, and exit" in body, (
        "worktree-agent.md must instruct the agent to call unregister_agent "
        "and exit after pr_merged. The per-task exit is the core of the "
        "one-task-per-session contract introduced by T-329."
    )


# ---------------------------------------------------------------------------
# worktree-agent.md — per-task work-log naming and bootstrap
# ---------------------------------------------------------------------------


def test_worktree_agent_documents_per_task_work_log_naming() -> None:
    """The per-task work-log file name pattern must appear in the agent template."""
    body = _read(WORKTREE_AGENT)
    assert "work-log-T-" in body, (
        "worktree-agent.md must document the per-task work-log file naming "
        "convention 'work-log-T-<NNN>.md'. This name is how the next session "
        "finds the handoff artifacts via the bootstrap glob."
    )


def test_worktree_agent_bootstrap_reads_prior_work_logs() -> None:
    """The bootstrap step must instruct agents to read prior work logs."""
    body = _read(WORKTREE_AGENT)
    assert "read them all" in body and "before any other action" in body, (
        "worktree-agent.md must contain a bootstrap step that instructs the "
        "agent to read all prior work-log-T-*.md files before any other action. "
        "This is the mechanism that restores context after a /clear between tasks."
    )


def test_worktree_agent_work_log_schema_has_required_frontmatter_keys() -> None:
    """The per-task work-log schema must document all required frontmatter keys."""
    body = _read(WORKTREE_AGENT)
    for key in ("task:", "title:", "pr:", "merged_at:"):
        assert key in body, (
            f"worktree-agent.md per-task work-log schema is missing frontmatter "
            f"key '{key}'. The schema test in test_per_task_work_log_schema.py "
            f"validates actual files against these keys — the template must document "
            f"what the validator enforces."
        )


def test_worktree_agent_work_log_schema_has_required_sections() -> None:
    """The per-task work-log schema must document all required section headers."""
    body = _read(WORKTREE_AGENT)
    for section in (
        "## What shipped",
        "## Files touched",
        "## Decisions",
        "## Review findings + resolutions",
        "## Learnings",
        "## Residual TODOs",
    ):
        assert section in body, (
            f"worktree-agent.md per-task work-log schema is missing section "
            f"'{section}'. This section is required by the schema validator and "
            f"must be documented in the template."
        )


def test_worktree_agent_residual_todos_is_load_bearing() -> None:
    """The 'Residual TODOs' section must be called out as load-bearing."""
    body = _read(WORKTREE_AGENT)
    assert "load-bearing" in body, (
        "worktree-agent.md must call out the 'Residual TODOs / context the next "
        "task should know' section as load-bearing — it is the primary handoff "
        "between sessions and agents must know to write it carefully."
    )


# ---------------------------------------------------------------------------
# launch SKILL.md — prompt template must have the hard-exit contract
# ---------------------------------------------------------------------------


def test_launch_skill_prompt_template_no_get_my_tasks_continuation() -> None:
    """The launch prompt template step 13 must not instruct get_my_tasks + next task."""
    body = _read(LAUNCH_SKILL)
    assert "get_my_tasks` and start the next `backlog` task" not in body, (
        "launch SKILL.md prompt template step 13 must not contain the old "
        "'get_my_tasks and start the next backlog task' instruction. The "
        "template now describes the hard-exit-after-one-task contract."
    )


def test_launch_skill_has_continuation_prompt_section() -> None:
    """The launch SKILL must document the continuation prompt for supervisor relaunches."""
    body = _read(LAUNCH_SKILL)
    assert "## Continuation Prompt" in body, (
        "launch SKILL.md must have a '## Continuation Prompt' section describing "
        "the prompt the supervisor uses when relaunching a worktree for task N+1."
    )


def test_launch_skill_has_supervisor_relaunch_flow() -> None:
    """The launch SKILL must document the supervisor relaunch flow."""
    body = _read(LAUNCH_SKILL)
    assert "## Supervisor Relaunch Flow" in body, (
        "launch SKILL.md must document the supervisor's relaunch decision: "
        "check for backlog tasks → relaunch (continuation prompt) or close-wave."
    )


def test_launch_skill_one_task_per_session_stated() -> None:
    """The launch SKILL must state the one-task-per-session contract."""
    body = _read(LAUNCH_SKILL)
    assert "One task per session" in body, (
        "launch SKILL.md must explicitly state the one-task-per-session contract "
        "so agents and readers understand why the prompt template ends at pr_merged."
    )


# ---------------------------------------------------------------------------
# close-wave SKILL.md — Step 5d must handle per-task log files
# ---------------------------------------------------------------------------


def test_close_wave_step5d_handles_per_task_logs() -> None:
    """Close-wave Step 5d must check for and consolidate per-task work logs."""
    body = _read(CLOSE_WAVE_SKILL)
    assert "work-log-T-" in body, (
        "close-wave SKILL.md Step 5d must reference the per-task work-log "
        "file pattern 'work-log-T-*.md'. These files are the primary source "
        "for the wave work log consolidation step."
    )


def test_close_wave_documents_supervisor_relaunch_boundary() -> None:
    """Close-wave must document when it runs vs when the supervisor relaunches."""
    body = _read(CLOSE_WAVE_SKILL)
    assert "Supervisor relaunch vs close-wave boundary" in body, (
        "close-wave SKILL.md Step 5d must document the boundary: the supervisor "
        "relaunches when backlog tasks remain; close-wave runs only when all tasks "
        "are resolved. Without this, operators may run close-wave prematurely."
    )


# ---------------------------------------------------------------------------
# setup SKILL.md — supervisor agent_unregistered handler
# ---------------------------------------------------------------------------


def test_setup_skill_documents_agent_unregistered_relaunch() -> None:
    """The setup SKILL must document how the supervisor handles agent_unregistered."""
    body = _read(SETUP_SKILL)
    assert "agent_unregistered` — relaunch or close-wave" in body, (
        "setup SKILL.md must document the supervisor's agent_unregistered handler: "
        "check for remaining backlog tasks → relaunch (continuation prompt) or "
        "hand off to close-wave. This is the supervisor half of T-329's design."
    )


def test_setup_skill_relaunch_uses_continuation_prompt() -> None:
    """The setup SKILL's relaunch instruction must reference work-log files."""
    body = _read(SETUP_SKILL)
    assert "work-log-T-*.md" in body, (
        "setup SKILL.md's relaunch instruction must include work-log-T-*.md in "
        "the continuation prompt so the new session bootstraps with prior context."
    )
