---
name: reconcile
description: Run system reconciliation check to detect and fix drift between board state, agents, PRs, worktrees, and branches. Always auto-fixes issues found — no separate "fix" step.
user-invocable: true
---

# System Reconciliation

Detect and fix drift across the multi-agent system. You MUST use MCP tools for all board/agent operations and git/gh CLI for infrastructure checks. Never use curl or direct API calls.

## Step 1: Register

You must be registered to use MCP tools. Call `mcp__cloglog__register_agent` with the current working directory as `worktree_path`.

## Step 2: Detect Repo

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
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
- Agents with zero active tasks (not done) — should unregister
- Tasks assigned to a worktree that no longer exists (check with `git worktree list`)

### Check 3: Worktrees vs branches

Run `git worktree list --porcelain` and for each worktree beyond the main one:
- Check if its branch is fully merged into main: `git branch --merged main | grep <branch>`
- If merged — can be removed

### Check 4: Stale branches

- **Local**: `git branch --merged main` — any non-main branches that aren't attached to active worktrees can be deleted
- **Remote**: `git fetch --prune origin`, then for each remote branch check if it has an open PR (`gh pr list --head <branch> --state open --json number -q length`). If no open PR and merged into main — stale

### Check 5: Orphaned PRs

Run `gh pr list --state open --json number,title,headRefName`. For each, verify the branch still exists with `git rev-parse --verify origin/<branch>`. If branch is gone — orphaned PR.

## Step 4: Present Report

Format the report with clear sections. Use checkmarks for healthy items and warnings for issues. End with a summary count.

## Step 5: Auto-Fix

Always fix issues automatically — no separate "fix" step. For each issue found:

- **Stale worktrees**: `git worktree remove --force <path>`, then delete the local branch with `git branch -D <branch>`
- **Stale zellij tabs**: find tabs for removed worktrees via `zellij action query-tab-names`, close with `zellij action close-tab`
- **Stale local branches**: `git branch -d <branch>`
- **Stale remote branches**: use bot token — `git push origin --delete <branch>`
- **Orphaned PRs**: close with bot token — `GH_TOKEN="$BOT_TOKEN" gh pr close <num> --comment "Closed by reconciliation: branch no longer exists"`
- **Merged PR + task in review**: flag for user — agents cannot mark tasks done
- **Stale agents**: call `mcp__cloglog__unregister_agent` for own registration; flag others for manual cleanup
- **Pull merged changes**: always run `git pull origin main` at the end to ensure local main is current

Report what was fixed and what needs manual attention.

## Step 6: Unregister

After the reconciliation is complete, call `mcp__cloglog__unregister_agent` to clean up your own registration.
