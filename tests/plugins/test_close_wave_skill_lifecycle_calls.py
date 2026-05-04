"""T-395 pin: ``close-wave/SKILL.md`` MUST wire the close-off task
through the new no-PR lifecycle (``start_task`` → ``update_task_status done``).

T-395 replaced the old PR-based lifecycle with a direct-to-main commit;
the close-off task terminal state changed from ``review + pr_merged=True``
(requiring a user drag to done) to ``done`` (marked directly by the
close-wave supervisor). The three required lifecycle calls are:

1. Resolve close-off task UUIDs (Step 1) — without this, none of the
   downstream lifecycle calls have a ``task_id`` to operate on.
2. ``mcp__cloglog__start_task`` on the primary close-off task (Step 9.7) —
   marks the task ``in_progress`` before the direct-to-main commit so the
   board reflects active close-wave progress.
3. ``mcp__cloglog__update_task_status`` to ``"done"`` (Step 13.5) —
   marks every close-off task done after the push succeeds. The
   close-off-task carve-out in ``src/agent/services.py`` permits
   agent-driven ``done`` transitions when ``task.close_off_worktree_id``
   is non-null.

These pins are presence checks; absence-pins on prior advisory patterns
would not catch a *deletion* of the wiring, which is the regression mode
that matters here.
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


def test_close_wave_skill_calls_start_task_for_primary_close_off() -> None:
    body = _read()
    assert "mcp__cloglog__start_task" in body, (
        "close-wave SKILL.md must call mcp__cloglog__start_task on the "
        "primary close-off task (Step 9.7) before the direct-to-main "
        "commit. This marks the task in_progress so the board reflects "
        "that close-wave is active."
    )
    # Order check: start_task must appear before the ALLOW_MAIN_COMMIT commit.
    start_pos = body.index("mcp__cloglog__start_task")
    commit_pos = body.index("ALLOW_MAIN_COMMIT=1 git commit")
    assert start_pos < commit_pos, (
        "mcp__cloglog__start_task must appear in the SKILL.md *before* "
        "the ALLOW_MAIN_COMMIT=1 git commit invocation. Step 9.7 "
        "must run before the commit (Step 13) so the board shows the "
        "task in_progress during the commit window."
    )


def test_close_wave_skill_marks_close_off_tasks_done() -> None:
    body = _read()
    assert "update_task_status" in body, (
        "close-wave SKILL.md must call mcp__cloglog__update_task_status "
        "in Step 13.5 to mark close-off tasks done after the direct push. "
        "Without this the row stays in_progress forever."
    )
    # Must use "done" status — not "review"
    assert '"done"' in body, (
        'close-wave SKILL.md Step 13.5 must use status: "done" for '
        "close-off tasks. T-395 replaced the old review+pr_url terminal "
        "state with a direct done transition enabled by the "
        "close_off_worktree_id carve-out in src/agent/services.py."
    )
    # update_task_status with done must appear AFTER the ALLOW_MAIN_COMMIT commit
    commit_pos = body.index("ALLOW_MAIN_COMMIT=1 git commit")
    done_pos = body.rindex('"done"')
    assert commit_pos < done_pos, (
        "update_task_status with done must follow the direct-to-main "
        "commit in the SKILL.md so tasks are only marked done after "
        "the push succeeds."
    )
