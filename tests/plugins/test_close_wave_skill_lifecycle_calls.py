"""T-371 pin: ``close-wave/SKILL.md`` MUST wire the close-off task
through the standard task lifecycle (``start_task`` →
``update_task_status review`` → done via the existing ``pr_merged``
webhook fan-out).

Pre-T-371 close-wave had **zero** MCP lifecycle calls — confirmed by
grep at the time the ticket was filed. The "Close worktree wt-..."
backlog rows accumulated indefinitely (T-355, T-357, T-359, T-361,
T-364, T-366, T-369) because nothing ever moved them out of backlog.

The skill's three required calls are:

1. Resolve close-off task UUIDs (Step 1) — without this, none of the
   downstream lifecycle calls have a ``task_id`` to operate on.
2. ``mcp__cloglog__start_task`` before branch creation (Step 9.7) —
   needed both to mark the task in_progress AND to satisfy the T-371
   ``require-task-for-pr.sh`` PreToolUse blocker that hard-rejects
   ``gh pr create`` without an in_progress task.
3. ``mcp__cloglog__update_task_status`` to ``"review"`` with ``pr_url``
   (Step 13.5) — moves every close-off task in the wave to ``review``
   so the ``pr_merged`` webhook flips ``pr_merged=True`` automatically.

These pins are presence checks; absence-pins on the prior advisory
patterns would not catch a *deletion* of the new wiring, which is the
regression mode that matters here.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = REPO_ROOT / "plugins/cloglog/skills/close-wave/SKILL.md"


def _read() -> str:
    assert SKILL.exists(), f"{SKILL} missing"
    return SKILL.read_text(encoding="utf-8")


def test_close_wave_skill_resolves_close_off_task_ids() -> None:
    body = _read()
    # The Step 1 sub-step must mention reading the board for
    # `Close worktree <wt>` titles and capturing the UUID.
    assert "Close worktree" in body, (
        "close-wave SKILL.md must reference the close-off task title "
        "string `Close worktree <wt-name>` so Step 1 has a deterministic "
        "way to resolve each worktree's task UUID."
    )
    assert "close_off_task_ids" in body or "PRIMARY_CLOSE_TASK_ID" in body, (
        "close-wave SKILL.md must capture the resolved close-off task "
        "UUIDs into a named variable (close_off_task_ids / "
        "PRIMARY_CLOSE_TASK_ID) so Steps 9.7 and 13.5 have something "
        "to operate on. Without an explicit handle the lifecycle calls "
        "have no task_id."
    )


def test_close_wave_skill_calls_start_task_before_branch_creation() -> None:
    body = _read()
    assert "mcp__cloglog__start_task" in body, (
        "close-wave SKILL.md must call mcp__cloglog__start_task on the "
        "primary close-off task before Step 10's branch creation. The "
        "T-371 require-task-for-pr.sh hook hard-blocks gh pr create "
        "(exit 2) without an in_progress task; skipping this call "
        "makes Step 13's gh pr create fail."
    )
    # Order check: start_task must appear before the gh pr create line.
    start_pos = body.index("mcp__cloglog__start_task")
    gh_create_pos = body.index("gh pr create --base main --head wt-close-")
    assert start_pos < gh_create_pos, (
        "mcp__cloglog__start_task must appear in the SKILL.md *before* "
        "the gh pr create invocation. The hook reads the board state "
        "at the moment gh pr create runs, so a start_task documented "
        "after the PR-creation block does not satisfy the blocker."
    )


def test_close_wave_skill_moves_close_off_tasks_to_review_with_pr_url() -> None:
    body = _read()
    assert "update_task_status" in body, (
        "close-wave SKILL.md must call mcp__cloglog__update_task_status "
        "after gh pr create to move the close-off task(s) to review "
        "with pr_url set. Without this the row stays in_progress / "
        "backlog forever and the pr_merged webhook has nothing to "
        "flip."
    )
    # Make sure update_task_status appears AFTER gh pr create.
    update_pos = body.rindex("update_task_status")
    gh_create_pos = body.index("gh pr create --base main --head wt-close-")
    assert gh_create_pos < update_pos, (
        "update_task_status must follow gh pr create in the SKILL.md "
        "so the call uses the URL the PR creation just produced."
    )
    # Look for the explicit "review" + pr_url combo somewhere after gh pr create.
    tail = body[gh_create_pos:]
    assert '"review"' in tail and "pr_url" in tail, (
        "The post-PR update_task_status snippet must move the task to "
        '"review" with `pr_url=<PR_URL>`. T-371 acceptance: a close-wave '
        "run end-to-end leaves the close-off task in done with pr_url "
        "set, which only happens if review-with-pr_url is the explicit "
        "call shape."
    )
