---
name: close-wave
description: Close a wave of worktrees after PRs merge. Handles PR verification, cooperative shutdown of worktree agents, work-log generation, teardown of worktrees/branches/tabs, quality gate on the close-wave branch, and learnings extraction.
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

## Invocation modes

This skill runs in one of two modes:

1. **User-driven** (`/cloglog close-wave [worktrees...]`) — the default.
   Walks Steps 1–14 including user confirmation. Wave name is derived from
   existing work logs (`wave-N.md`).
2. **Reconcile delegation** — `plugins/cloglog/skills/reconcile/SKILL.md`
   Step 5.0 hands off a single cleanly-completed worktree after verifying
   the three-part predicate: (a) `shutdown-artifacts/work-log.md` exists,
   (b) a `Close worktree <wt-name>` task exists in `backlog`, and (c)
   every assigned task is resolved from the agent's side — i.e.
   `status == "done"`, OR `status == "review"` with `pr_merged == True`,
   OR `status == "review"` with `pr_url is None` (no-PR task via
   `skip_pr=True` per `docs/design/agent-lifecycle.md` §1 Trigger B).
   See reconcile SKILL.md Step 5.0 for the full predicate specification;
   a stricter "`pr_merged=True` everywhere" reading would falsely reject
   cleanly-completed worktrees whose last task shipped no-PR. Reconcile
   is the system's arbiter: close-wave is the clean path,
   `force_unregister` is the dirty path, and delegation ensures the two
   stop fighting over teardown (T-270; see
   `docs/design/agent-lifecycle.md` §5 for the unified-flow spec).

### When invoked from reconcile

Call shape from reconcile's Step 5.0:

```
close-wave(worktree="<wt-name>", invoked_from="reconcile")
```

The reconcile entry point diverges from the user-driven flow in three
places and runs Steps 2–14 unchanged otherwise:

- **Skip Step 1.5 — user confirmation.** Reconcile has already declared
  the auto-fix path (`/cloglog reconcile` always fixes, no separate
  confirm step); re-prompting the user would stall the automation.
- **Single-worktree scope.** Reconcile passes exactly one `wt-*` name.
  Treat it as a single-worktree wave — no multi-worktree fan-out, no
  auto-detection pass against `git worktree list`.
- **Override wave-name derivation (Step 4).** Set the `<wave-name>`
  variable to `reconcile-<wt-name>`; Step 4's file-shape contract
  (`docs/work-logs/<date>-<wave-name>.md`) is preserved, and close-wave
  emits `docs/work-logs/<date>-reconcile-<wt-name>.md`. Reconcile
  invocations are orphan cleanups, not natural waves, so the normal
  `wave-N` counter derivation is skipped (using it would falsely
  advance the counter and break the next user-driven `/cloglog
  close-wave` numbering). The `<date>` prefix and `.md` suffix are
  still produced by Step 4 itself, not by the override — the override
  is a `<wave-name>` substitution, not a full filename replacement.

**Callable from reconcile** — everything else (Steps 2, 3, 5, 5a–5d, 6,
7, 8, 9, 9.5, 10, 10.5, 11, 12, 13, 14) is identical to the user-driven
mode. The cooperative shutdown, shutdown-artifact consolidation into
the work log, worktree/branch/tab removal, quality gate on the
`wt-close-*` branch, and learnings extraction all run unchanged. Anything close-wave does today for a
single worktree is the correct behaviour for reconcile's case — the
delegation is a pure entry-point change, not a refactor of the pipeline.

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

### Step 5a — Resolve worktree_id, snapshot inbox offset, request shutdown (tier 1)

Call `mcp__cloglog__list_worktrees()` once up front and build a map
`worktree_path → {id, name, branch_name, status, last_heartbeat}` for
every worktree in this project. This map survives supervisor restarts,
unlike the `.cloglog/inbox` file (`plugins/cloglog/hooks/agent-shutdown.sh`
truncates it when the main agent exits). For each git-detected worktree
in scope, look up its `id` in the map — that's the UUID to pass to
`mcp__cloglog__request_shutdown`.

Resolve the supervisor inbox BEFORE calling `request_shutdown` — `git
rev-parse --show-toplevel` would return the worktree path when run
inside a worktree (see CLAUDE.md "Inside a worktree, `git rev-parse
--show-toplevel` returns the worktree path, not the main clone.");
the main clone is always the parent of `--git-common-dir`:

```bash
MAIN_INBOX="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.cloglog/inbox"
# Capture the offset BEFORE request_shutdown — a fast/idle agent can emit
# agent_unregistered in the gap between the MCP call returning and the
# wait helper starting. Binding the window to the offset-before-shutdown
# makes that event still count.
SINCE_OFFSET=$(stat -c %s "$MAIN_INBOX" 2>/dev/null || echo 0)
```

Then:

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

```bash
uv run python scripts/wait_for_agent_unregistered.py \
    --worktree "<wt-name>" \
    --inbox "$MAIN_INBOX" \
    --since-offset "$SINCE_OFFSET" \
    --timeout 120
```

The helper reads events appended at or after `SINCE_OFFSET`, so a fast
agent's `agent_unregistered` that landed between `request_shutdown` and
the helper launch is still observed (verified in
`tests/test_wait_for_agent_unregistered.py`).

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
git fetch origin
git merge --ff-only origin/main
```

A non-fast-forward state means real divergence (e.g., a stray local-`main` commit) — investigate, do not paper over with a merge commit.

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

## Step 10: Open a close-wave branch

The dev clone now has a writable local `main`, so the main agent uses the same `wt-*` branch + PR flow as every other agent (no detached-HEAD push, no direct-`main` commit). See `docs/design/prod-branch-tracking.md` §7.

```bash
git checkout -b wt-close-<date>-<wave-name>
```

Use today's date (`$(date -I)`) and the wave name from Step 1 (e.g., `wt-close-2026-04-26-wave-3` or `wt-close-2026-04-26-reconcile-wt-foo` for reconcile-delegated runs). All Step 11/12/13 edits (quality-gate fixes, work log, learnings) land on this branch — never on `main`.

The dev clone's pre-commit hook (installed once via `scripts/install-dev-hooks.sh`) rejects commits on `main` unless `ALLOW_MAIN_COMMIT=1` is set. If you find yourself reaching for that override here, stop — the right answer is the branch above.

## Step 10.5: Run Quality Gate

Read the quality command from `.cloglog/config.yaml` if it exists, otherwise fall back to `make quality`. Run it and fix any issues before proceeding.

Common post-merge problems:
- Import errors from models not being imported
- Lint/format issues from merged code
- Type errors from interface mismatches

If the quality gate fails, fix the issues on the `wt-close-*` branch from Step 10 — these are integration issues that individual worktrees cannot detect, and they ship via the same PR as the work log and learnings update.

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

## Step 13: Commit, push, and PR

Commit all fixes, work log, and CLAUDE.md updates to the `wt-close-<date>-<wave-name>` branch from Step 10. Push the branch and open a PR against `main` using the **exact `Push + Create PR` sequence** from `plugins/cloglog/skills/github-bot/SKILL.md` — every `git push` and every `gh` invocation MUST go through the bot identity. A bare `gh pr create` falls back to the operator's personal `gh auth` and breaks the bot-identity invariant the github-bot skill exists to enforce; only the bot-authenticated form below is correct:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git"
git push -u origin HEAD
GH_TOKEN="$BOT_TOKEN" gh pr create --base main --head wt-close-<date>-<wave-name> \
  --title "chore(close-wave): <wave-name>" \
  --body "<work-log path + learnings summary, with the standard Demo + Test Report sections>"
```

Auto-merge applies per `plugins/cloglog/skills/github-bot/SKILL.md` "Auto-Merge on Codex Pass" once codex review and CI checks pass. After merge, fast-forward main and drop the local branch:

```bash
git checkout main
git fetch origin
git merge --ff-only origin/main
git branch -D wt-close-<date>-<wave-name>
```

A non-fast-forward state means real divergence — investigate, do not paper over with a merge commit.

Never commit directly to `main`. The dev clone's pre-commit hook (`scripts/install-dev-hooks.sh`) blocks that path; the `ALLOW_MAIN_COMMIT=1` override exists only for emergency-rollback cherry-picks, not for close-wave.

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
