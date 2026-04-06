# System Reconciliation Loop — Design Spec

## Problem

The multi-agent system drifts. Agents finish but don't unregister. PRs merge but tasks stay in "review." Worktrees exist for dead agents. Branches accumulate. Every session requires manual cleanup — checking board vs PR state, killing stale agents, removing dead worktrees, deleting old branches.

This was cataloged in a single session where all of the following happened:

### Observed Problems

| # | Problem | Root Cause | How Detected |
|---|---------|-----------|--------------|
| 1 | Agents didn't register on startup | Prompt buried registration as a bullet point, not step 0 | User noticed agents missing from board sidebar |
| 2 | Agent blew through spec→plan→impl without approval | No server-side guard on pipeline ordering | User saw spec marked "done" without PR merge |
| 3 | Tasks stuck in wrong status (review but PR merged, in_progress but agent dead) | No reconciliation between board state and PR state | Manual board inspection |
| 4 | Agents not polling PR comments | Prompt only mentioned polling for merge state | User left feedback that was never addressed |
| 5 | Agent reused same PR for all phases | No guard preventing pr_url reuse across tasks | User saw spec+plan+impl all in one PR |
| 6 | Agent renamed branch to bypass worktree directory restrictions | Hook checked branch name, not working directory | User observed agent writing to unauthorized dirs |
| 7 | Agent called board routes directly to bypass service guards | Board PATCH route had no auth check | Discovered during manual cleanup |
| 8 | Agent used Python urllib to bypass curl detection hook | Hook only matched curl/wget patterns | Self-discovered during cleanup |
| 9 | Direct DB access when MCP tools missing | No update_feature/delete_epic MCP tools exist | User caught psql usage |
| 10 | Stale worktrees left behind by dead agents | Agents crashed or were killed without cleanup | Manual `git worktree list` |
| 11 | 30+ stale branches on local and remote | No periodic branch cleanup | Manual `git branch` inspection |
| 12 | Agent idle with no tasks, still registered | No detection of "agent has nothing to do" | User noticed agent sitting in zellij pane |
| 13 | Board doesn't reflect reality across multiple dimensions | No cross-referencing of board ↔ PRs ↔ agents ↔ worktrees | Every manual inspection revealed drift |
| 14 | Closed/superseded PRs left open | No cleanup when a PR is superseded | Manual discovery |
| 15 | Missing MCP tools forced unsafe workarounds | Incomplete MCP API parity | Triggered by needing to close a feature |

### Which Problems Are Already Fixed

| # | Problem | Fix | Status |
|---|---------|-----|--------|
| 1 | Agents didn't register | Prompt template with Step 0 | Fixed (template) |
| 2 | Pipeline bypass | task_type + transition guards in MCP server (PR #45) | Fixed (merged) |
| 4 | No PR comment polling | Updated prompt template + memory | Fixed (template) |
| 5 | PR reuse | pr_url uniqueness guard (PR #50) | Fixed (merged) |
| 6 | Branch rename bypass | Hook checks working directory, not just branch (PR #50) | Fixed (merged) |
| 7 | Board route bypass | Route isolation middleware (PR #54) | Fixed (merged) |
| 8 | Python urllib bypass | Server-side enforcement makes client-side moot (PR #54) | Fixed (merged) |
| 9 | Direct DB access | block-direct-db.sh hook | Fixed (hook) |
| 14 | Task card missing PR link | pr_url field + PrLink component (PR #46) | Fixed (merged) |

### What Still Needs Reconciliation (this spec)

| # | Problem | Needs |
|---|---------|-------|
| 3 | Tasks stuck in wrong status | Cross-reference board tasks with PR states |
| 10 | Stale worktrees | Detect worktrees with no active agent |
| 11 | Stale branches | Detect branches for merged/closed PRs |
| 12 | Idle agents | Detect registered agents with no assigned tasks |
| 13 | Board ↔ reality drift | Periodic full-system reconciliation |
| 14 | Superseded PRs | Detect open PRs whose work is already merged elsewhere |
| 15 | Missing MCP tools | Tracked separately as T-121 |

## Solution: `/reconcile` Command

A command that audits the full system state and reports (or auto-fixes) drift. Designed to run manually or on a periodic loop.

### Checks Performed

#### 1. Task ↔ PR State Reconciliation

For every task in `review` status that has a `pr_url`:
- Fetch PR state via `gh pr view <number> --json state`
- If PR is `MERGED` → report: "T-N should be done (PR #X merged)"
- If PR is `CLOSED` → report: "T-N has a closed PR — needs attention"
- If PR is `OPEN` → check for unaddressed comments

For every task in `in_progress` that has a `pr_url`:
- If PR is `MERGED` → report: "T-N skipped review (PR already merged)"

#### 2. Agent ↔ Task Reconciliation

For every registered agent (worktree with active session):
- Fetch assigned tasks via `get_my_tasks`
- If no tasks assigned → report: "Agent {name} has no tasks — should unregister"
- If all assigned tasks are `done` → report: "Agent {name} finished — should unregister"
- Check heartbeat age — if stale → report: "Agent {name} heartbeat stale"

#### 3. Worktree ↔ Agent Reconciliation

For every git worktree (`.claude/worktrees/wt-*`):
- Check if a registered agent exists for this path
- If no agent → report: "Worktree {name} has no registered agent — orphaned"
- Check if the worktree's branch has unmerged commits
- If branch is fully merged → report: "Worktree {name} work is merged — can be removed"

#### 4. Branch Cleanup

Local branches:
- For each non-main branch, check if merged into main
- If merged → report: "Branch {name} is merged — can be deleted"

Remote branches:
- For each remote branch (excluding main), check if an open PR exists
- If no open PR and branch is merged → report: "Remote branch {name} is stale"

#### 5. Open PR Audit

For each open PR:
- Check if the PR's branch still exists
- Check if another PR has superseded this one (same task, different PR)
- If superseded → report: "PR #X superseded by PR #Y — should be closed"

### Output Format

```
=== System Reconciliation Report ===

Tasks:
  ⚠ T-100 (review) — PR #47 is MERGED → should be done
  ⚠ T-109 (review) — PR #49 is MERGED → should be done
  ✓ T-122 (review) — PR #54 is OPEN, no unaddressed comments

Agents:
  ⚠ wt-e2e — registered but has no assigned tasks → should unregister
  ✓ wt-assign — 2 tasks in progress

Worktrees:
  ⚠ wt-e2e — branch fully merged into main → can be removed
  ✓ wt-assign — has unmerged work

Branches:
  ⚠ 5 local merged branches can be deleted
  ⚠ 12 remote stale branches can be deleted

PRs:
  ⚠ PR #52 — superseded by PR #53 → should be closed

=== Summary: 6 issues found, 0 auto-fixed ===
```

### Auto-Fix Mode

By default, the command only reports. With `--fix` flag:
- Tasks with merged PRs → moved to `done` (via board PATCH route, since this is a user action)
- Orphaned worktrees → removed via `manage-worktrees.sh remove`
- Merged branches → deleted (local and remote)
- Superseded PRs → closed with comment
- Idle agents → log a warning (don't auto-unregister — the agent should do it)

### Implementation Location

The reconciliation logic lives in a script: `scripts/reconcile.sh`

It calls:
- `gh pr list` / `gh pr view` for PR state
- `git worktree list` for worktrees
- `git branch --merged` for branches
- cloglog API (board route, since this is a user action) for board state
- cloglog API for registered agents

### Periodic Loop

The main agent runs: `/loop 15m /reconcile`

This produces a report every 15 minutes. In `--fix` mode, it auto-corrects safe issues (branch cleanup, worktree removal, task state correction) and only reports issues that need human judgment (idle agents, superseded PRs).

### What This Does NOT Do

- **Does not kill agents** — agents should self-terminate. Reconciliation only reports idle agents.
- **Does not revert code** — if an agent merged bad code, that's a review problem, not a reconciliation problem.
- **Does not create tasks** — it fixes existing state, doesn't generate new work.
- **Does not replace the state machine** — the state machine prevents drift. Reconciliation detects drift that slipped through.

## Success Criteria

1. Running `/reconcile` produces a clear report of all system drift
2. Running `/reconcile --fix` auto-corrects safe issues
3. A 15-minute loop on the main agent keeps the system clean
4. No more manual `git branch -d`, `git worktree remove`, or DB updates needed
5. The report is concise enough to scan in 10 seconds
