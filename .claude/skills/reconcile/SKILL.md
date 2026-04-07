---
name: reconcile
description: "Run a system reconciliation check to detect and fix drift between the board, agents, PRs, worktrees, and branches. Use this skill when the user says /reconcile, asks to check system health, wants to find stale agents or orphaned worktrees, or suspects drift between board state and reality."
user-invocable: true
---

# System Reconciliation

Run the reconciliation script to detect drift across the cloglog multi-agent system. This checks five categories:

1. **Tasks** — board tasks in review/in_progress whose PRs are already merged or closed
2. **Agents** — registered agents with no active tasks (should unregister)
3. **Worktrees** — git worktrees whose branches are fully merged (can be removed)
4. **Branches** — local and remote branches that are merged and stale
5. **PRs** — open PRs whose branches no longer exist

## Usage

Run the script from the repo root:

```bash
scripts/reconcile.sh
```

This produces a report showing issues found. If there are fixable issues, suggest running with `--fix`:

```bash
scripts/reconcile.sh --fix
```

The `--fix` flag auto-corrects safe issues:
- Moves tasks to `done` when their PR is merged
- Removes worktrees whose branches are fully merged
- Deletes stale local and remote branches
- Closes PRs whose branches no longer exist

## Prerequisites

The backend must be running (`make run-backend`) for task and agent checks to work. If it's not running, mention that task/agent checks were skipped and only git-level checks ran.

## After running

Summarize the report for the user. Highlight anything that needs manual attention (e.g., PRs with unaddressed comments, closed PRs that need investigation). If `--fix` was used, report what was auto-fixed.
