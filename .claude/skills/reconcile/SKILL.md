---
name: reconcile
description: "Run a system reconciliation check to detect and fix drift between the board, agents, PRs, worktrees, and branches. Use this skill when the user says /reconcile, asks to check system health, wants to find stale agents or orphaned worktrees, or suspects drift between board state and reality."
user-invocable: true
---

# System Reconciliation

Detect and fix drift across the cloglog multi-agent system. You are an agent — you MUST use MCP tools for all board/agent operations and git/gh CLI for infrastructure checks. Never use curl or direct API calls.

## Step 1: Register

You must be registered to use MCP tools. Call `mcp__cloglog__register_agent` with the current working directory as `worktree_path`.

## Step 2: Run checks

Run all five checks and collect issues. Present results as a structured report.

### Check 1: Tasks vs PR state

Use `mcp__cloglog__get_board` to get all tasks. For each task in `review` or `in_progress` that has a `pr_url`:
- Extract the PR number and check its state with `gh pr view <num> --json state -q .state`
- **MERGED + task in review** → issue: task should be done (only user can move to done — flag it)
- **MERGED + task in in_progress** → issue: task stuck, PR already merged
- **CLOSED + task in review** → issue: PR was closed, needs attention
- **OPEN** → check for unaddressed comments: get last push date with `gh pr view <num> --json commits -q '.commits[-1].committedDate'`, then count comments after that date with `gh api repos/sachinkundu/cloglog/issues/<num>/comments --jq "[.[] | select(.created_at > \"<date>\")] | length"`

### Check 2: Agents vs tasks

Use `mcp__cloglog__get_board` — the board response includes worktree/agent info on tasks. Look for:
- Agents with zero active tasks (not done) → should unregister
- Tasks assigned to a worktree that no longer exists (check with `git worktree list`)

### Check 3: Worktrees vs branches

Run `git worktree list --porcelain` and for each worktree under `.claude/worktrees/wt-*`:
- Check if its branch is fully merged into main: `git branch --merged main | grep <branch>`
- If merged → can be removed with `./scripts/manage-worktrees.sh remove <name>`

### Check 4: Stale branches

- **Local**: `git branch --merged main` — any non-main, non-wt-* branches can be deleted
- **Remote**: `git fetch --prune origin`, then for each remote branch check if it has an open PR (`gh pr list --head <branch> --state open --json number -q length`). If no open PR and merged into main → stale

### Check 5: Orphaned PRs

Run `gh pr list --state open --json number,title,headRefName`. For each, verify the branch still exists with `git rev-parse --verify origin/<branch>`. If branch is gone → orphaned PR.

## Step 3: Present report

Format the report with clear sections. Use checkmarks for healthy items and warnings for issues. End with a summary count.

## Step 4: Fix (only if user passed "fix" as an argument)

If the user asked to fix issues:
- **Stale worktrees**: run `./scripts/manage-worktrees.sh remove <name>`
- **Stale local branches**: `git branch -d <branch>`
- **Stale remote branches**: `git push origin --delete <branch>`
- **Orphaned PRs**: close with `gh pr close <num> --comment "Closed by reconciliation: branch no longer exists"` (use bot token — see CLAUDE.md "Git Identity & PRs")
- **Merged PR + task in review**: tell the user to drag the card to done on the board (agents cannot mark tasks done)
- **Stale agents**: call `mcp__cloglog__unregister_agent` (this unregisters the current agent — for other agents, flag for manual cleanup)

Report what was fixed and what needs manual attention.

## Step 5: Unregister

After the reconciliation is complete, call `mcp__cloglog__unregister_agent` to clean up your own registration.
