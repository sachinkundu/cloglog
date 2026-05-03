---
name: close-wave
description: Close a wave of worktrees after PRs merge. Handles PR verification, cooperative shutdown of worktree agents, work-log generation, teardown of worktrees/branches/tabs, quality gate on the close-wave branch, and learnings extraction.
user-invocable: true
---

# Close Wave

Close a wave of worktrees after all PRs are merged. Handles the full cleanup
lifecycle using the **cooperative shutdown** protocol from
`${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §2 and §5.

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
   `skip_pr=True` per `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §1 Trigger B).
   See reconcile SKILL.md Step 5.0 for the full predicate specification;
   a stricter "`pr_merged=True` everywhere" reading would falsely reject
   cleanly-completed worktrees whose last task shipped no-PR. Reconcile
   is the system's arbiter: close-wave is the clean path,
   `force_unregister` is the dirty path, and delegation ensures the two
   stop fighting over teardown (T-270; see
   `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §5 for the unified-flow spec).

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

1. Run `git worktree list --porcelain` to find active worktrees. **Filter to only worktrees whose path starts with `$(git rev-parse --show-toplevel)/.claude/worktrees/`.** Skip the main worktree and any worktree outside that directory — in particular, the prod worktree at `.cloglog/config.yaml: prod_worktree_path` must never be touched by close-wave.
2. If `$ARGUMENTS` specifies worktree names, filter to only those.
3. If no worktrees exist, tell the user there's nothing to close.
4. Determine the wave name by examining existing work logs to figure out the current numbering (e.g., if `wave-1.md` exists, this is `wave-2`).
5. **Resolve each worktree's close-off task UUID.** Call `mcp__cloglog__get_board()` and, for every `wt-<name>` in scope, find the task with `title == f"Close worktree {wt-name}"` and `status == "backlog"`. Capture the task UUID into a per-worktree map `close_off_task_ids[wt-name] → task_uuid`. The first entry's UUID is `PRIMARY_CLOSE_TASK_ID` — that's the one Step 9.7 marks `in_progress` to satisfy the T-371 `gh pr create` blocker hook. If a worktree has no matching backlog close-off row, fail loud — do not paper over with `create_close_off_task`; the worktree was created before the close-off-row invariant existed and reconcile owns that gap (T-371 reconcile rule).
6. Show the user what was detected: wave name, worktree list, close-off task IDs. Ask for confirmation before proceeding.

## Step 2: Detect Repo

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
```

## Step 3: Verify PRs Are Merged

For each worktree, check if its PR has been merged:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests "${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py")
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
`${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §5. Cooperative shutdown lets the worktree
agent run its own Section 2 sequence — emit `agent_unregistered` with
absolute path to `shutdown-artifacts/work-log.md` (`artifacts.learnings` is `null` for T-329 agents — learnings are embedded in per-task work logs), call
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
uv run python "${CLAUDE_PLUGIN_ROOT}/scripts/wait_for_agent_unregistered.py" \
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
  `shutdown-artifacts/` into the work log: read `artifacts.work_log` via
  the absolute path carried in the event. Read `artifacts.learnings` only if non-null
  — for T-329 agents `artifacts.learnings` is `null` and learnings are embedded in
  the per-task `work-log-T-*.md` files (Step 5d); for legacy/backstop agents it is a
  real path. Never attempt to open a null path. The files vanish once the worktree is
  removed in Step 7.
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
re-issuing MCP calls that will now fail auth (§5 tier 2). **Always go
through `plugins/cloglog/hooks/lib/close-zellij-tab.sh`** — `zellij action
close-tab` takes no positional argument and closes the *focused* tab, so
a bare `close-tab` after `query-tab-names` has twice killed the
supervisor's own tab (T-339). The helper resolves the target by name,
refuses (exit 2) if it would close the focused tab, and only then issues
a tab-id-scoped close.

```bash
"${CLAUDE_PLUGIN_ROOT}/hooks/lib/close-zellij-tab.sh" "<wt-name>"
rc=$?
# rc=0 → tab closed (or absent, idempotent).
# rc=2 → would have closed the supervisor's own tab. Surface as a hard
#        error in the work log's Shutdown summary; the supervisor must
#        focus a different tab and re-run, NOT silently retry. Never
#        fall back to a bare `zellij action close-tab`.
```

Record the fallback in the work log's **Shutdown summary** under the
worktree's row: path used (`cooperative` vs `force_unregister`), timeout,
and — if applicable — a note that shutdown-artifacts were reconstructed
from PRs/commits rather than read from the worktree.

### Step 5d — Consolidate shutdown artifacts

For each worktree that completed tier 1 successfully:

1. Check for **per-task work logs**: `ls <worktree_path>/shutdown-artifacts/work-log-T-*.md`. If any exist, read each one in task-number order — they are the canonical source of what shipped, files touched, decisions, and learnings for each task. Each file follows the schema:
   ```
   ---
   task: T-NNN
   title: <task title>
   pr: <pr-url>
   merged_at: <utc-iso>
   ---
   ## What shipped / ## Files touched / ## Decisions /
   ## Review findings + resolutions / ## Learnings / ## Residual TODOs
   ```

2. Also read the aggregate `shutdown-artifacts/work-log.md` (pointed to by the `agent_unregistered` event's `artifacts.work_log` field) — it is the concatenation of per-task logs plus a one-line envelope header. Use it when per-task logs are absent (older worktrees) or as a consistency check.

3. Inline all per-task work logs into the wave work log, one section per task, in task-number order. Mark the source clearly (`from work-log-T-NNN.md`). Do this BEFORE Step 7 removes the worktree — the files vanish with the worktree.

For worktrees that fell back to tier 2, reconstruct the per-worktree section
from `git log --oneline main..<branch>` and the merged PR body, and mark it
`reconstructed (force_unregister)` so future readers know there is no
original work log.

**Supervisor relaunch vs close-wave boundary.** Close-wave runs only when *all* tasks assigned to a worktree are resolved (done or review-with-pr-merged). If the supervisor relaunched the same worktree for multiple tasks across multiple sessions, all per-task logs from each session are present in `shutdown-artifacts/` by the time the final agent exits and close-wave runs. Do not run close-wave while a worktree still has `backlog` tasks — the supervisor's `agent_unregistered` handler (see the `launch` skill's **Supervisor Relaunch Flow** section) is responsible for relaunching until all tasks are done, at which point it hands off to close-wave.

## Step 6: Sanity check — no running launcher

For each worktree that unregistered via tier 1, verify the launcher process
has actually exited (`pgrep -f "<worktree-path>"` should return nothing).

T-352 wired a PostToolUse hook
(`plugins/cloglog/hooks/exit-on-unregister.sh`) on
`mcp__cloglog__unregister_agent` that schedules a TERM to claude on
successful unregister, so the launcher's `wait` returns naturally.
**A surviving Claude process after a tier-1 unregister should never
happen.** If `pgrep` returns a PID, treat it as a bug: capture the
process tree (`ps -ef --forest`), the launcher's debug log
(`/tmp/agent-shutdown-debug.log`), and the worktree's
`shutdown-artifacts/` directory, file an issue, and only then close
the zellij tab. Do NOT `kill -9` silently — that hides the regression.

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
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests "${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py")
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
`${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §6 — pause, write `need_session_restart` to
the main inbox, wait for a tab relaunch (no MCP hot-reload exists; the tool
list is cached at session start).

## Step 9.7: Mark the primary close-off task in_progress (T-371)

Before any branch creation or `gh pr create` invocation, mark the
**primary close-off task** (Step 1's `PRIMARY_CLOSE_TASK_ID`)
`in_progress` so the wave's PR has a board task linked to it from the
moment it is opened:

```
mcp__cloglog__start_task(task_id: "<PRIMARY_CLOSE_TASK_ID>")
```

This call is mandatory. The T-371 `require-task-for-pr.sh` PreToolUse
hook hard-blocks `gh pr create` (exit 2) when no task is `in_progress`
for this working directory, so skipping this step makes Step 13's
`gh pr create` fail with the hook's actionable error. **Do not** try
to start more than one close-off task here — `start_task` enforces
"one active task per agent" (`src/agent/services.py::start_task`).
Multi-worktree waves move the remaining close-off tasks straight from
`backlog` → `review` in Step 13.5 with the same `pr_url`; that
transition does not require an intermediate `in_progress` step
(`update_task_status` only checks `pr_url` for the `review` move,
`src/agent/services.py:526`).

If `start_task` returns `task_blocked` because pipeline ordering or
feature-deps cite an upstream task that has not finished, **that is a
real bug — stop the wave** and resolve the blocker rather than
papering over with `force_unregister`. Close-off tasks have no
predecessors by design (`src/board/templates.py`), so a `task_blocked`
here is a regression in the close-off template.

## Step 10: Open a close-wave branch

The dev clone now has a writable local `main`, so the main agent uses the same `wt-*` branch + PR flow as every other agent (no detached-HEAD push, no direct-`main` commit). See `docs/design/prod-branch-tracking.md` §7.

Step 9 fetched and fast-forwarded `main`, but Step 9.5 (`make sync-mcp-dist`) runs between Step 9 and here, and any PR merged in that window (e.g., an implementation PR merged in another tab while close-wave was running) silently invalidates Step 9's fast-forward. **Always re-fetch immediately before creating the branch** so the close-wave branch base includes every merged commit:

```bash
git fetch origin
git merge --ff-only origin/main
git checkout -b wt-close-<date>-<wave-name>
```

A non-fast-forward state means real divergence — investigate, do not paper over with a merge commit.

Use today's date (`$(date -I)`) and the wave name from Step 1 (e.g., `wt-close-2026-04-26-wave-3` or `wt-close-2026-04-26-reconcile-wt-foo` for reconcile-delegated runs). All Step 11/12/13 edits (quality-gate fixes, work log, learnings) land on this branch — never on `main`.

The dev clone's pre-commit hook (installed once via `${CLAUDE_PLUGIN_ROOT}/scripts/install-dev-hooks.sh`) rejects commits on `main` unless `ALLOW_MAIN_COMMIT=1` is set. If you find yourself reaching for that override here, stop — the right answer is the branch above.

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
- **Route each learning to its proper home — never back into `CLAUDE.md`'s
  Agent Learnings section (T-368 retired it).** The routing rules:
  - **Silent-failure invariants** (a rule whose breakage ships through
    lint/typecheck/tests undetected and only fails in production) →
    `docs/invariants.md`. New entries require a pin test; if you don't
    have one, file a follow-up task instead of adding the entry.
  - **Workflow / SKILL gotchas** (something a worktree agent or supervisor
    should do differently) → the relevant
    `plugins/cloglog/skills/<skill>/SKILL.md` (or
    `plugins/cloglog/templates/AGENT_PROMPT.md` for cross-skill agent
    behaviour, or `plugins/cloglog/agents/<agent>.md` for subagent
    behaviour).
  - **Architectural / design decisions** → the matching design /
    architecture doc — most live under `docs/design/` (e.g.
    `docs/design/prod-branch-tracking.md`), with the DDD context map at
    `docs/ddd-context-map.md` (top-level, not under `docs/design/`).
  - **Top-level project rules that every contributor must read** —
    `CLAUDE.md` (only for the rare structural rule, not session-specific
    gotchas).
  - **One-off fixes / meta observations** → drop. Not every learning
    deserves persistence.

## Step 12: Complete Work Log

Fill in the "Learnings & Issues" section of the work log with:
- What integration issues were found and fixed.
- What tests passed/failed initially.
- What patterns future agents should follow or avoid.
- For any tier-2 fallback: root cause (wedged MCP call? hung plan subagent?)
  and what hardening would prevent a repeat.

Fill in "State After This Wave" with what's now implemented and verified working.

## Step 13: Commit, push, and PR

Commit all fixes, the work log, and any learnings routed by Step 11 (to `docs/invariants.md`, the relevant `plugins/cloglog/**/SKILL.md`, a design doc under `docs/design/`, or — rarely — `CLAUDE.md`) on the `wt-close-<date>-<wave-name>` branch from Step 10. Push the branch and open a PR against `main` using the **exact `Push + Create PR` sequence** from `plugins/cloglog/skills/github-bot/SKILL.md` — every `git push` and every `gh` invocation MUST go through the bot identity. A bare `gh pr create` falls back to the operator's personal `gh auth` and breaks the bot-identity invariant the github-bot skill exists to enforce; only the bot-authenticated form below is correct:

```bash
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests "${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py")
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git" "HEAD:${BRANCH}"
git fetch origin "${BRANCH}"
git branch --set-upstream-to=origin/${BRANCH}
GH_TOKEN="$BOT_TOKEN" gh pr create --base main --head wt-close-<date>-<wave-name> \
  --title "chore(close-wave): <wave-name>" \
  --body "<work-log path + learnings summary, with the standard Demo + Test Report sections>"
```

### Step 13.5: Move close-off tasks to review (T-371)

Capture the PR URL returned by `gh pr create` (or read it back via
`gh pr view --json url -q .url`). Then, for **every** close-off task
UUID resolved in Step 1's `close_off_task_ids` map, call:

```
mcp__cloglog__update_task_status(task_id: "<close_task_id>", status: "review", pr_url: "<PR_URL>")
```

The primary task transitions `in_progress` → `review`; remaining tasks
go `backlog` → `review` directly (the `review` guard at
`src/agent/services.py:526` only checks for a `pr_url`, no
intermediate `in_progress` is required). All close-off tasks share the
same `pr_url` — the wave PR fulfils all of them — and the existing
`pr_merged` webhook fan-out flips `pr_merged=True` on each row when
the PR merges.

**Terminal state — `review + pr_merged=True`, awaiting user drag.**
Close-off rows follow the standard agent task lifecycle: agents move
tasks to `review` with a `pr_url`, the merge webhook flips
`pr_merged=True`, and the **user** drags the card to `done` on the
board (`src/agent/services.py:502-508` rejects any agent attempt to
move tasks to `done`; this is the load-bearing user-only-done
invariant). T-371 originally framed acceptance as "leaves the
close-off task in `done` with no manual operator step", but
implementing a system-owned automatic merge → done transition would
violate that invariant project-wide. The narrowed acceptance — `review
+ pr_merged=True`, user drags as the single closing click — matches
how every other reviewed task ships in this project.

Auto-merge applies per `plugins/cloglog/skills/github-bot/SKILL.md` "Auto-Merge on Codex Pass" once codex review and CI checks pass. After merge, fast-forward main and drop the local branch:

```bash
git checkout main
git fetch origin
git merge --ff-only origin/main
git branch -D wt-close-<date>-<wave-name>
```

A non-fast-forward state means real divergence — investigate, do not paper over with a merge commit.

Never commit directly to `main`. The dev clone's pre-commit hook (`${CLAUDE_PLUGIN_ROOT}/scripts/install-dev-hooks.sh`) blocks that path; the `ALLOW_MAIN_COMMIT=1` override exists only for emergency-rollback cherry-picks, not for close-wave.

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

## Gotcha: `gh pr merge --delete-branch` exit code from a worktree

`gh pr merge --delete-branch` exits non-zero from a worktree when `main`
is checked out by the parent clone — the squash merge succeeds
server-side, but the local post-merge cleanup (`git checkout main && git
branch -D <branch>`) fails with `fatal: 'main' is already used by
worktree at '<parent>'`, masking the successful merge. Do not panic on a
non-zero exit — verify with the `pr_merged` inbox event or `gh pr view
<num> --json state,mergedAt`. If you need clean post-merge state on the
worktree side, do the ff-and-prune from the main clone, not as a
side-effect of `gh pr merge`.

## Gotcha: pytest subprocess with extra deps

When a test subprocess in a closing wave needs packages not in the test
venv (`requests`, `PyJWT[crypto]`), `[sys.executable, str(script)]`
resolves to `.venv/bin/python3` which lacks them and fails under
`--cov=src`. Use `["uv", "run", "--with", "PyJWT[crypto]", "--with",
"requests", "python", str(script)]` so dependencies are resolved at run
time.
