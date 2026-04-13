---
name: reconcile
description: Run system reconciliation — check each agent's state, verify PRs merged, clean up finished agents (worktree, tabs, branches). Always auto-fixes.
user-invocable: true
---

# System Reconciliation

Check every agent, verify their work is done, clean up what's finished. Simple loop:

1. Get all agents
2. For each: are they done? (PR merged, no active tasks)
3. If done: clean up everything
4. Pull main

## Step 1: Setup

Register to use MCP tools:
```bash
mcp__cloglog__register_agent with current working directory
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
```

Pull main first so merged branches are detected:
```bash
git pull origin main
git fetch --prune origin
```

## Step 2: Get Agent State

Get the board and list of project worktrees:
- `mcp__cloglog__get_board` — all tasks with their worktree assignments and PR URLs
- `git worktree list --porcelain` — filter to this project's `.claude/worktrees/` only
- `zellij action list-tabs` — all zellij tabs

Build a picture of each agent: worktree name, assigned tasks, task statuses, PR URLs, PR merge state.

For each task with a `pr_url`, check the PR:
```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
GH_TOKEN="$BOT_TOKEN" gh pr view <num> --json state -q .state
```

## Step 3: For Each Agent — Is It Done?

An agent is done if ALL of these are true:
- All its assigned tasks have PRs that are merged (or task is already done)
- The agent has unregistered (offline) OR has no remaining active tasks
- The worktree branch is merged into main

## Step 4: Clean Up Finished Agents

For each agent that's done, clean up everything in this order:

1. **Close zellij tab**: find `wt-*` tab via `zellij action list-tabs`, close with `zellij action close-tab --tab-id <ID>`
2. **Run project teardown**: `WORKTREE_PATH=<path> WORKTREE_NAME=<name> .cloglog/on-worktree-destroy.sh` if it exists
3. **Remove worktree**: `git worktree remove --force <path>`
4. **Delete local branch**: `git branch -D <branch>`
5. **Delete remote branch**: `git push origin --delete <branch>` (use bot token)
6. **Flag task for user**: if task is still in `review`, tell the user to move it to done

## Step 5: Clean Up Orphans

After processing agents, sweep for leftovers:

- **Stale `wt-*` zellij tabs** with no matching worktree on disk — close them
- **Stale local branches** merged into main with no worktree — `git branch -d`
- **Stale remote branches** merged into main with no open PR — `git push origin --delete` (bot token)
- **Orphaned open PRs** whose branch no longer exists — `GH_TOKEN="$BOT_TOKEN" gh pr close <num>`
- **Features with all tasks done** — flag for user to mark feature as done

## Step 6: Report

Show what was found and what was cleaned up:

| Agent | Tasks | PR State | Action |
|-------|-------|----------|--------|
| wt-inbox-shutdown | T-179 | #114 merged | cleaned up: tab, worktree, branches |
| wt-deprioritize-btn | T-185 | #115 merged | cleaned up: tab, worktree, branches |

Summary: N agents cleaned up, N stale branches deleted, N tabs closed, N items need manual attention.

## Step 7: Unregister

Call `mcp__cloglog__unregister_agent` to clean up own registration.
