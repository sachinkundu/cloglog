"""Board task templates.

A template is a stored title + description instantiated with a fresh
task number per use. Templates are plain Python constants until there is
a second one — at that point promote to a DB-backed registry (see the
T-246 design spec).
"""

from __future__ import annotations


def close_worktree_template(worktree_name: str) -> tuple[str, str]:
    """Return ``(title, description)`` for the close-off task.

    The description is verbatim from the T-246 spec so every auto-filed
    close-off card reads identically. If you edit the steps here, update
    the spec in ``AGENT_PROMPT.md`` / the F-48 feature description too —
    supervisors consult both.
    """
    title = f"Close worktree {worktree_name}"
    description = (
        f"Close-off for worktree {worktree_name}.\n"
        "\n"
        "1. Verify all assigned tasks are done (or in review with "
        "pr_merged=true) on the board. The agent_unregistered event in "
        "the main inbox carries `tasks_completed` and a `prs` map "
        "(T-NNN -> PR URL) — use it to attribute merges per task without "
        "shelling out to `gh pr list`.\n"
        "2. Read shutdown-artifacts/{work-log,learnings}.md from the "
        "worktree.\n"
        "3. Archive both to "
        "docs/work-logs/YYYY-MM-DD-<wave>-{work-log,learnings}.md.\n"
        "4. File any plugin-level / repo-level learnings as backlog "
        "tasks (do NOT bake into this PR).\n"
        "5. Update CLAUDE.md if any project-local gotcha emerged worth "
        "carrying forward.\n"
        "6. Run on-worktree-destroy.sh, git worktree remove, branch -D, "
        "drop the worktree DB.\n"
        "7. Open a PR with this task's id; webhook events for that PR "
        "will route here.\n"
        "8. Move this task to review on PR open; user moves to done "
        "after merge."
    )
    return title, description


CLOSE_OFF_EPIC_TITLE = "Operations"
CLOSE_OFF_FEATURE_TITLE = "Worktree Close-off"
