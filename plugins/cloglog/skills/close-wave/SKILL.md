---
name: close-wave
description: Close a wave of worktrees after PRs merge. Handles PR verification, cooperative shutdown of worktree agents, work-log generation, teardown of worktrees/branches/tabs, quality gate on main, and learnings extraction.
user-invocable: true
---

# Close Wave

Close a wave of worktrees after all PRs are merged. Handles the full cleanup
lifecycle using the **cooperative shutdown** protocol from
`docs/design/agent-lifecycle.md` §2 and §5.

**Usage:**
```
/cloglog close-wave                    # auto-detect active worktrees
/cloglog close-wave wt-f12 wt-f13     # specific worktrees only
```

Arguments: `$ARGUMENTS` — optional list of worktree names. If omitted, auto-detect all active worktrees.

## Step 1: Detect Worktrees

1. Run `git worktree list --porcelain` to find active worktrees. **Filter to only worktrees whose path starts with `$(git rev-parse --show-toplevel)/.claude/worktrees/`.** Skip the main worktree and any worktree outside that directory (e.g., `../cloglog-prod` is the prod worktree — never touch it).
2. If `$ARGUMENTS` specifies worktree names, filter to only those.
3. If no worktrees exist, tell the user there's nothing to close.
4. Determine the wave name by examining existing work logs to figure out the current numbering (e.g., if `wave-1.md` exists, this is `wave-2`).
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

## Step 4: Generate Work Log Skeleton

Create a work log file (location configurable, default `docs/work-logs/<date>-<wave-name>.md`) with:
- For each worktree: commits (`git log --oneline main..<branch>`), files changed (`git diff --name-only main..<branch>`), PR number and title.
- A **Shutdown summary** section with one row per worktree, to be filled in during Step 5.
- Leave "Learnings & Issues" and "State After This Wave" sections to be filled after verification.

## Step 5: Cooperative Shutdown (replaces kill-by-PID + close-tab)

For each worktree, run the **tier-1 → tier-2** sequence from
`docs/design/agent-lifecycle.md` §5. Cooperative shutdown lets the worktree
agent run its own Section 2 sequence — emit `agent_unregistered` with
absolute paths to `shutdown-artifacts/{work-log.md,learnings.md}`, call
`unregister_agent`, and stop — so the close-wave flow gets a usable work log
and a clean backend state.

**Never use `kill <pid>` on the launcher, and never close the zellij tab
before the worktree is unregistered.** A killed launcher reparents its child
Claude process (see B-2 / T-217) and bypasses the shutdown hook; closing the
tab before the backend session ends leaves the worktree row dangling until
the tier-3 heartbeat sweep.

### Step 5a — Request shutdown (tier 1)

For each worktree, look up its `worktree_id` (from the board / the
`agent_started` inbox event the supervisor recorded at launch), then:

```
mcp__cloglog__request_shutdown(worktree_id: "<uuid>")
```

The MCP tool writes a `{"type":"shutdown","reason":"pr_merged"}` line to the
worktree's inbox (`<worktree_path>/.cloglog/inbox`). The agent's `Monitor`
delivers the event in under a second; the agent runs §2 (mark_pr_merged →
review → report_artifact → shutdown-artifacts → emit `agent_unregistered`
→ `unregister_agent`).

Record the request timestamp per worktree so the work log can cite it.

### Step 5b — Wait for `agent_unregistered` (up to 120 s per worktree)

Run the wait helper against the **main** inbox (`$(git rev-parse --show-toplevel)/.cloglog/inbox`):

```bash
uv run python scripts/wait_for_agent_unregistered.py \
    --worktree "<wt-name>" \
    --inbox "$(git rev-parse --show-toplevel)/.cloglog/inbox" \
    --timeout 120
```

The helper only matches events appended AFTER it starts, so pre-existing
`agent_unregistered` lines from prior sessions do not satisfy the wait
(verified in `tests/test_wait_for_agent_unregistered.py`).

Exit codes:
- **0** — the worktree emitted `agent_unregistered`. Consolidate its
  `shutdown-artifacts/` into the work log (read `work_log` and `learnings`
  via the absolute paths carried in the event; the files vanish once the
  worktree is removed in Step 7).
- **1** — timeout. Go to Step 5c (fallback). Do NOT proceed to Step 7 for
  this worktree yet.
- **2** — inbox path wrong. Stop the whole close-wave and tell the user
  the supervisor inbox is misconfigured; do not force-unregister anything.

### Step 5c — Fallback to force_unregister (tier 2, timeout only)

Only when Step 5b exits 1 (cooperative timeout):

```
mcp__cloglog__force_unregister(worktree_id: "<uuid>")
```

Then, and only then, close the zellij tab to stop the wedged agent from
re-issuing MCP calls that will now fail auth (§5 tier 2). Finding the tab:

```bash
zellij action query-tab-names
# Close the tab whose name matches this worktree (never close the one
# you're running in).
zellij action close-tab
```

Record the fallback in the work log's **Shutdown summary** under the
worktree's row: path used (`cooperative` vs `force_unregister`), timeout,
and — if applicable — a note that shutdown-artifacts were reconstructed
from PRs/commits rather than read from the worktree.

### Step 5d — Consolidate shutdown artifacts

For each worktree that completed tier 1 successfully, copy or inline its
`shutdown-artifacts/work-log.md` and `shutdown-artifacts/learnings.md` into
the wave work log BEFORE Step 7 removes the worktree. The inbox event's
`artifacts.work_log` and `artifacts.learnings` values are absolute paths —
use them directly.

For worktrees that fell back to tier 2, reconstruct the per-worktree section
from `git log --oneline main..<branch>` and the merged PR body, and mark it
`reconstructed (force_unregister)` so future readers know there is no
original work log.

## Step 6: Sanity check — no running launcher

For each worktree that unregistered via tier 1, verify the launcher process
has actually exited (`pgrep -f "<worktree-path>"` should return nothing).
If a Claude process is still attached — rare, but possible if the agent
hung after `unregister_agent` — note it and close its zellij tab. Do NOT
`kill -9` silently; a surviving process after tier-1 unregister is a bug
worth surfacing in the work log's Learnings section.

## Step 7: Remove Worktrees and Local Branches

Only after the worktree has unregistered (tier 1 success or tier 2
fallback). For each worktree:

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
- Read each PR's description and review comments.
- Read the consolidated Step 5d shutdown-artifacts (the real source of
  learnings the agents wrote themselves).
- Identify patterns, gotchas, or rules that future agents should know.
- Update the project CLAUDE.md with new learnings if any are found.

## Step 12: Complete Work Log

Fill in the "Learnings & Issues" section of the work log with:
- What integration issues were found and fixed.
- What tests passed/failed initially.
- What patterns future agents should follow or avoid.
- For any tier-2 fallback: root cause (wedged MCP call? hung plan subagent?)
  and what hardening would prevent a repeat.

Fill in "State After This Wave" with what's now implemented and verified working.

## Step 13: Commit and Push

Commit all fixes, work log, and CLAUDE.md updates to main using the bot identity (via the github-bot skill). Push as bot.

## Step 14: Summary

Print a summary table showing:

| Worktree | PR | Shutdown path | Commits |
|----------|-----|----------------|---------|
| wt-... | #42 | cooperative | 5 |
| wt-... | #43 | force_unregister (timeout) | 3 |

- Integration verification: pass/fail, issues found and fixed.
- Work log location.
- New learnings added.
- What's ready for the next wave.
