# F-26: System Reconciliation Loop

*2026-04-06T12:39:52Z by Showboat 0.6.1*
<!-- showboat-id: 3796f6d2-ef27-47de-b621-d25218384fb6 -->

Run the reconciliation script in report mode to detect system drift:

```bash
scripts/reconcile.sh 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
```

```output
=== System Reconciliation Report ===

Tasks:
  ✓ No tasks with PRs in review/in_progress

Agents:
  ✓ Agent cloglog — 1 active task(s)
  ⚠ Agent wt-e2e — no active tasks assigned → should unregister

Worktrees:
  ✓ No active worktrees

Branches:
  ✓ No stale local branches
  ✓ No stale remote branches

PRs:
  ✓ No open PRs

=== Summary: 1 issue(s) found, 0 auto-fixed ===

Run with --fix to auto-correct safe issues:
  scripts/reconcile.sh --fix
```
