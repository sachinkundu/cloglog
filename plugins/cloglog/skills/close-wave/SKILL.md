---
name: close-wave
description: Close a wave of worktrees after PRs merge. Handles PR verification, work log generation, cleanup of worktrees/branches/tabs, quality gate on main, and learnings extraction.
user-invocable: true
---

# Close Wave

Close a wave of worktrees after all PRs are merged. Handles the full cleanup lifecycle.

**Usage:**
```
/cloglog close-wave                    # auto-detect active worktrees
/cloglog close-wave wt-f12 wt-f13     # specific worktrees only
```

Arguments: `$ARGUMENTS` — optional list of worktree names. If omitted, auto-detect all active worktrees.

## Step 1: Detect Worktrees

1. Run `git worktree list --porcelain` to find active worktrees. **Filter to only worktrees whose path starts with `$(git rev-parse --show-toplevel)/.claude/worktrees/`.** Skip the main worktree and any worktree outside that directory (e.g., `../cloglog-prod` is the prod worktree — never touch it).
2. If `$ARGUMENTS` specifies worktree names, filter to only those
3. If no worktrees exist, tell the user there's nothing to close
4. Determine the wave name by examining existing work logs to figure out the current numbering (e.g., if `wave-1.md` exists, this is `wave-2`)
5. Show the user what was detected: wave name, worktree list. Ask for confirmation before proceeding.

## Step 2: Detect Repo

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
```

## Step 3: Verify PRs Are Merged

For each worktree, check if its PR has been merged:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
GH_TOKEN="$BOT_TOKEN" gh pr list --state merged --head <branch> --json number,title
```

If any PR is still open, STOP and tell the user which PRs need to be merged first.

## Step 4: Generate Work Log

Create a work log file (location configurable, default `docs/work-logs/<date>-<wave-name>.md`) with:
- For each worktree: commits (`git log --oneline main..<branch>`), files changed (`git diff --name-only main..<branch>`), PR number and title
- Leave "Learnings & Issues" and "State After This Wave" sections to be filled after verification

## Step 5: Kill Agent Processes

Find and kill any Claude processes running in the worktree directories:

```bash
# Find processes
pgrep -f "<worktree-path>"
# Kill gracefully
kill <pids>
# Wait, then force-kill survivors
sleep 2
kill -9 <pids> 2>/dev/null
```

Verify none remain.

## Step 6: Close Zellij Tabs

Use `zellij action query-tab-names` to find tabs associated with this wave's worktrees. Close them:

```bash
# Find tab IDs for worktree tabs
zellij action query-tab-names
# Close each worktree tab (never close the tab you're running in)
zellij action close-tab
```

## Step 7: Remove Worktrees and Local Branches

For each worktree:

```bash
git worktree remove --force <path>
git branch -D <branch>
```

Verify with `git worktree list`.

## Step 8: Clean Remote Branches

For each worktree branch, delete the remote branch using the bot identity:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git" --delete <branch>
```

Skip branches that are already gone.

## Step 9: Update Main

```bash
git checkout main
git pull origin main
```

## Step 9.5: Sync MCP Server Dist (T-244)

Any merged PR that touched `mcp-server/src/**` changed the MCP tool surface,
but `mcp-server/dist/` is gitignored and every worktree's `.mcp.json` points
at the main clone's compiled artifact. After pulling main, rebuild dist and
notify any still-running worktrees so they know their cached tool list is
stale:

```bash
make sync-mcp-dist
```

The script rebuilds `mcp-server/dist/` via `npm run build`, diffs the tool
names before/after, and appends an `mcp_tools_updated` event to every online
worktree's `.cloglog/inbox` plus the main agent inbox. It is a no-op when the
tool surface did not change, so it is safe to run on every close-wave.

A running worktree agent that receives the event follows the protocol in
`docs/design/agent-lifecycle.md` §6 — pause, write `need_session_restart` to
the main inbox, wait for a tab relaunch (no MCP hot-reload exists; the tool
list is cached at session start).

## Step 10: Run Quality Gate

Read the quality command from `.cloglog/config.yaml` if it exists, otherwise fall back to `make quality`. Run it and fix any issues before proceeding.

Common post-merge problems:
- Import errors from models not being imported
- Lint/format issues from merged code
- Type errors from interface mismatches

If the quality gate fails, fix the issues directly on main — these are integration issues that individual worktrees cannot detect.

## Step 11: Extract Learnings

Spawn a subagent to review all merged PRs and extract learnings:
- Read each PR's description and review comments
- Identify patterns, gotchas, or rules that future agents should know
- Update the project CLAUDE.md with new learnings if any are found

## Step 12: Complete Work Log

Fill in the "Learnings & Issues" section of the work log with:
- What integration issues were found and fixed
- What tests passed/failed initially
- What patterns future agents should follow or avoid

Fill in "State After This Wave" with what's now implemented and verified working.

## Step 13: Commit and Push

Commit all fixes, work log, and CLAUDE.md updates to main using the bot identity (via the github-bot skill). Push as bot.

## Step 14: Summary

Print a summary table showing:

| Worktree | PR | Status | Commits |
|----------|-----|--------|---------|
| wt-... | #42 | cleaned | 5 |
| wt-... | #43 | cleaned | 3 |

- Integration verification: pass/fail, issues found and fixed
- Work log location
- New learnings added
- What's ready for the next wave
