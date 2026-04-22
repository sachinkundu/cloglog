---
name: reconcile
description: Run system reconciliation check to detect and fix drift between board state, agents, PRs, worktrees, and branches. Always auto-fixes issues found — no separate "fix" step.
user-invocable: true
---

# System Reconciliation

Detect and fix drift across the multi-agent system. You MUST use MCP tools
for all board/agent operations and git/gh CLI for infrastructure checks.
Never use curl or direct API calls.

Worktree teardown during auto-fix uses the **cooperative shutdown** protocol
from `docs/design/agent-lifecycle.md` §2 and §5 — the same tier-1 →
tier-2 sequence the close-wave skill follows. Reconcile never kills
launchers by PID and never closes zellij tabs before the backend session
has ended.

## Step 1: Register

You must be registered to use MCP tools. Call `mcp__cloglog__register_agent` with the current working directory as `worktree_path`.

## Step 2: Detect Repo

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
MAIN_INBOX="$(git rev-parse --show-toplevel)/.cloglog/inbox"
```

## Step 3: Run Checks

Run all five checks and collect issues. Present results as a structured report.

### Check 1: Tasks vs PR state

Use `mcp__cloglog__get_board` to get all tasks. For each task in `review` or `in_progress` that has a `pr_url`:
- Extract the PR number and check its state with `gh pr view <num> --json state -q .state`
- **MERGED + task in review** — issue: task should be done (only user can move to done — flag it)
- **MERGED + task in in_progress** — issue: task stuck, PR already merged
- **CLOSED + task in review** — issue: PR was closed, needs attention
- **OPEN** — check for unaddressed comments: get last push date with `gh pr view <num> --json commits -q '.commits[-1].committedDate'`, then count comments after that date with `gh api repos/${REPO}/issues/<num>/comments --jq "[.[] | select(.created_at > \"<date>\")] | length"`

### Check 2: Agents vs tasks

Use `mcp__cloglog__get_board` — the board response includes worktree/agent info on tasks. Look for:
- Agents with zero active tasks (not done) — eligible for cooperative shutdown (Step 5, "drained-agent" case).
- Tasks assigned to a worktree that no longer exists.
- Agents with no heartbeat in the last N minutes (wedged-agent case for Step 5).

**IMPORTANT:** Only check worktrees that belong to THIS project. Project worktrees live under `$(git rev-parse --show-toplevel)/.claude/worktrees/`. Use `git worktree list --porcelain` and **filter to only entries whose path starts with your project's `.claude/worktrees/` directory**. Ignore worktrees from other tools (claude-squad, vibe-kanban, etc.) or other projects entirely.

### Check 3: Worktrees vs branches

Run `git worktree list --porcelain` and **filter to only worktrees under this project's `.claude/worktrees/` directory**. For each:
- Check whether an agent is registered on that worktree (via `get_board`'s worktree info).
- Check whether its branch is fully merged into main: `git branch --merged main | grep <branch>`.
- Classify into one of the Step 5 cases: `pr_merged_still_registered`, `orphaned_worktree_no_agent`, or `healthy` (skip).

**Never touch worktrees outside your project's directory.** Other tools manage their own worktrees.

### Check 4: Stale branches

- **Local**: `git branch --merged main` — any non-main branches that aren't attached to active worktrees can be deleted.
- **Remote**: `git fetch --prune origin`, then for each remote branch check if it has an open PR (`gh pr list --head <branch> --state open --json number -q length`). If no open PR and merged into main — stale.

### Check 5: Orphaned PRs

Run `gh pr list --state open --json number,title,headRefName`. For each, verify the branch still exists with `git rev-parse --verify origin/<branch>`. If branch is gone — orphaned PR.

## Step 4: Present Report

Format the report with clear sections. Use checkmarks for healthy items and warnings for issues. End with a summary count.

## Step 5: Auto-Fix

Always fix issues automatically — no separate "fix" step. For each issue
found, follow the rule that matches its class. **All worktree teardown goes
through the cooperative path first; `force_unregister` is only for truly
unreachable agents or orphaned worktrees where no agent is registered.**

### Case A — PR merged, agent still registered

Same as close-wave's primary path.

1. `mcp__cloglog__request_shutdown(worktree_id)`.
2. Wait up to 120 s for `agent_unregistered` on the main inbox:
   ```bash
   uv run python scripts/wait_for_agent_unregistered.py \
       --worktree "<wt-name>" \
       --inbox "$MAIN_INBOX" \
       --timeout 120
   ```
3. On exit 0 — proceed to teardown (below).
4. On exit 1 — fall back: `mcp__cloglog__force_unregister(worktree_id)`;
   record `path: force_unregister (reconcile_pr_merged_timeout)` in the
   reconciliation report.

### Case B — Wedged agent (registered, no heartbeat / task stuck in_progress)

Try cooperative first; escalate quickly if the agent is truly unresponsive.

1. `mcp__cloglog__request_shutdown(worktree_id)` with reason `reconcile_wedged`
   (the MCP tool currently takes only `worktree_id`; note the reason in the
   report).
2. Wait briefly — a wedged MCP call is unlikely to return promptly, so a
   short timeout is appropriate:
   ```bash
   uv run python scripts/wait_for_agent_unregistered.py \
       --worktree "<wt-name>" \
       --inbox "$MAIN_INBOX" \
       --timeout 30
   ```
3. On exit 0 — the agent was not as wedged as it looked; proceed to teardown.
4. On exit 1 — `mcp__cloglog__force_unregister(worktree_id)`; record the
   escalation.

### Case C — Orphaned worktree (no agent registered but tab/branch/path exist)

Skip `request_shutdown` — there is no agent to respond. Skip cooperative
wait for the same reason.

1. `mcp__cloglog__force_unregister(worktree_id)` — this is idempotent and
   returns `{"already_unregistered": true}` when the worktree row is
   already gone, which is the expected shape for a truly orphaned entry.
2. Proceed directly to teardown.

### Teardown (all cases, after the agent is unregistered)

Only after the worktree has unregistered — by Case A success, Case B
fallback, or Case C.

- **Zellij tab**: find via `zellij action query-tab-names`, close with
  `zellij action close-tab` (never the tab you are running in).
- **Worktree path**: `git worktree remove --force <path>`. Run
  `.cloglog/on-worktree-destroy.sh` if it exists.
- **Local branch**: `git branch -D <branch>`.
- **Remote branch** (if stale per Check 4): use bot token — `git push origin --delete <branch>`.

### Other drift

- **Stale local branches without a worktree**: `git branch -d <branch>`
  (or `-D` if not merged).
- **Stale remote branches**: bot token — `git push origin --delete <branch>`.
- **Orphaned PRs**: close with bot token — `GH_TOKEN="$BOT_TOKEN" gh pr close <num> --comment "Closed by reconciliation: branch no longer exists"`.
- **Merged PR + task in review**: call `mcp__cloglog__mark_pr_merged` with
  the `task_id` to flip `pr_merged=True` (unblocks the `start_task` guard);
  then flag for user — only the user can move the task to done.
- **Pull merged changes**: always run `git pull origin main` at the end to
  ensure local main is current.

Report what was fixed and which path each worktree followed (cooperative vs
force_unregister) so the operator can tell at a glance whether any tier-2
escalations happened.

## Step 6: Unregister

After the reconciliation is complete, call `mcp__cloglog__unregister_agent` to clean up your own registration.
