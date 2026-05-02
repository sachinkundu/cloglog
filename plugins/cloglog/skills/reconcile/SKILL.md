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
from `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §2 and §5 — the same tier-1 →
tier-2 sequence the close-wave skill follows. Reconcile never kills
launchers by PID and never closes zellij tabs before the backend session
has ended.

## Step 1: Register

You must be registered to use MCP tools. Call `mcp__cloglog__register_agent` with the current working directory as `worktree_path`.

## Step 2: Detect Repo

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
# The supervisor inbox lives at <project_root>/.cloglog/inbox — `git
# rev-parse --show-toplevel` would return the worktree path when reconcile
# runs inside a worktree (see CLAUDE.md), so we resolve it via
# --git-common-dir which points at the main clone's .git directory in both
# worktree and main-clone contexts.
MAIN_INBOX="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")/.cloglog/inbox"
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

### Check 2: Build the worktree inventory

Call `mcp__cloglog__list_worktrees()` to get every `WorktreeResponse` in
the project — `{id, name, worktree_path, branch_name, status,
current_task_id, last_heartbeat, created_at}`. This is the authoritative
source for worktree metadata; `get_board` only carries `worktree_id` on
tasks and has no worktree status/heartbeat/path.

Run `git worktree list --porcelain` and **filter to only worktrees whose
path starts with the project root's `.claude/worktrees/` directory**
(never touch worktrees owned by claude-squad, vibe-kanban, a sibling
project, etc.). The project root is the parent of `--git-common-dir`:

```bash
PROJECT_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
```

Join the two sets by `worktree_path`. Also call `mcp__cloglog__get_board`
to get every task's `{status, pr_url, pr_merged, worktree_id}` so Case A
can match merged PRs to the right worktree.

### Drift classification

Classify each worktree against the joined data:

- **Case A — `pr_merged_still_registered`**. Task has `pr_merged=True`,
  `status=review`, a non-null `worktree_id`, and `list_worktrees` shows
  that worktree's `status=online`. The agent should have unregistered on
  the `pr_merged` webhook (§2) but did not. Run tier-1 cooperative
  shutdown; teardown on success.
- **Case B — wedged agent**. `list_worktrees` shows `status=online` but
  `last_heartbeat` is older than `heartbeat_timeout_seconds * 2` (the
  backend marks the session timed out at 1×; 2× is the "definitely
  wedged, not just a pending sweep" threshold). Run tier-1 cooperative
  shutdown with a short timeout (30 s — a wedged MCP call rarely
  recovers within the full 120 s window), then `force_unregister` on
  timeout.
- **Case C — orphaned worktree**. Filesystem path under
  `.claude/worktrees/` exists, and either (a) `list_worktrees` shows
  the matching row with `status=offline`, or (b) no row exists for the
  path. Skip tier-1 — there is no agent to respond. Call
  `mcp__cloglog__force_unregister(worktree_id)` (idempotent; returns
  `{"already_unregistered": true}` when the row is already gone) only
  when (a) applies. Then proceed directly to teardown.
- **Healthy** — worktree row `status=online`, heartbeat fresh, task not
  in the drift set. Skip.

### Check 4: Stale branches

- **Local**: `git branch --merged main` — any non-main branches that aren't attached to active worktrees can be deleted.
- **Remote**: `git fetch --prune origin`, then for each remote branch check if it has an open PR (`gh pr list --head <branch> --state open --json number -q length`). If no open PR and merged into main — stale.

### Check 5: Orphaned PRs

Run `gh pr list --state open --json number,title,headRefName`. For each, verify the branch still exists with `git rev-parse --verify origin/<branch>`. If branch is gone — orphaned PR.

## Step 4: Present Report

Format the report with clear sections. Use checkmarks for healthy items and warnings for issues. End with a summary count.

## Step 5: Auto-Fix

Always fix issues automatically — no separate "fix" step. For each issue
found, follow the rule that matches its class. **Worktree teardown goes
through the cooperative path first; `force_unregister` is only for the
cooperative-timeout fallback.**

Reconcile's auto-fixes are MCP / git-infrastructure calls — they do not
author committed file changes. If a fix surfaces a need to edit
committed files (e.g. patching a skill, CLAUDE.md, or a script), do
**not** commit on `main`. Branch first and ship via the standard
`wt-reconcile-*` PR flow, exactly the same shape every other agent
uses (see `docs/design/prod-branch-tracking.md` §7):

Push and PR via the **exact `Push + Create PR` sequence** from
`plugins/cloglog/skills/github-bot/SKILL.md` — a bare `gh pr create`
falls back to the operator's personal `gh auth` and breaks the
bot-identity invariant. Only the bot-authenticated form below is
correct:

```bash
git checkout -b wt-reconcile-<date>-<topic>
# edits + commit
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests "${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py")
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$||')
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git" "HEAD:${BRANCH}"
git fetch origin "${BRANCH}"
git branch --set-upstream-to=origin/${BRANCH}
GH_TOKEN="$BOT_TOKEN" gh pr create --base main --head wt-reconcile-<date>-<topic> \
  --title "chore(reconcile): <topic>" \
  --body "<what reconcile fixed and why>"
# after merge:
git checkout main && git fetch origin && git merge --ff-only origin/main
git branch -D wt-reconcile-<date>-<topic>
```

The dev clone's pre-commit hook (`${CLAUDE_PLUGIN_ROOT}/scripts/install-dev-hooks.sh`)
rejects commits on `main` unless `ALLOW_MAIN_COMMIT=1` is set; treat
that override as emergency-rollback-only, not as a reconcile shortcut.

### Step 5.0 — Close-wave delegation for cleanly-completed worktrees

BEFORE executing Case A / Case C teardown on any worktree in the drift set,
check the **completed-cleanly predicate** for that worktree. When it holds,
**delegate the entire teardown to close-wave** instead of running reconcile's
own teardown path. If reconcile tore down the worktree first, `git worktree
remove --force` would vaporize `<worktree_path>/shutdown-artifacts/` before
close-wave gets a chance to archive them to `docs/work-logs/` and route any
extracted learnings to their proper homes (`docs/invariants.md`, the
relevant SKILL/agent/template, a design doc, or — rarely — `CLAUDE.md`;
T-368 retired the `CLAUDE.md` Agent Learnings section). The exact
split-brain observed on 2026-04-23 during the T-268 close-out (T-270).

Reconcile is the arbiter: close-wave is the clean path (cleanly-completed
worktrees with artifacts), `force_unregister` is the dirty path (everything
else). See `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §5 for the unified-flow spec.

#### Completed-cleanly predicate

All three must hold for a worktree to be eligible for close-wave delegation:

1. **Shutdown artifact present.** `<worktree_path>/shutdown-artifacts/work-log.md`
   exists on disk. (Check with a plain `[ -f "<path>/shutdown-artifacts/work-log.md" ]`.)
2. **Close-off task queued.** A close-off task whose title equals
   `Close worktree <wt-name>` exists in `backlog` status. Match on the
   title string — NOT on `worktree_id`. The close-off task is created by
   `src/board/services.py::create_close_off_task` with two relevant
   fields: (a) `close_off_worktree_id` is the target worktree's UUID
   (the one reconcile is closing), and (b) `worktree_id` is the **main
   agent's** worktree_id — deliberately, so `get_my_tasks` surfaces the
   card in the main agent session that will execute the close-off.
   The `get_board` payload's `TaskCard` schema exposes `worktree_id`
   but NOT `close_off_worktree_id` (see
   `src/board/schemas.py::TaskResponse`), so filtering by
   `worktree_id == <target_wt_id>` would never match and filtering by
   `close_off_worktree_id` is not possible from the board payload. The
   deterministic match is title equality against the
   `close_worktree_template` output (`src/board/templates.py:20`):
   `title == f"Close worktree {wt_name}"` AND `status == "backlog"`.
3. **Every assigned task is resolved from the agent's side.** This is
   the project completion contract from `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md`
   §1 and the close-off template in `src/board/templates.py:24-25`
   ("all assigned tasks are done (or in review with pr_merged=true)"),
   not a stricter `pr_merged=True` everywhere check. The predicate is
   satisfied when, for every task whose `worktree_id` matches this
   worktree, at least one of the following holds:
   - `status == "done"` — user has moved it across (the board's
     post-agent terminal state), OR
   - `status == "review"` AND `pr_merged == True` — the PR merged and
     the task is awaiting the user's drag to `done` (T-218 / §1), OR
   - `status == "review"` AND `pr_url is None` — a no-PR task (plan,
     docs-only) that shipped via `update_task_status(..., skip_pr=True)`
     per §1 Trigger B; the task has no PR to merge so `pr_merged` stays
     `False` by design.

   Equivalently: **no task assigned to this worktree is in `backlog` or
   `in_progress`, and no task is in `review` with a `pr_url` whose
   `pr_merged == False`.** A stricter "every task has `pr_merged=True`"
   check would falsely reject cleanly-completed worktrees whose last
   task was no-PR, or whose user already dragged one task to `done`,
   recreating the T-270 artifact-loss bug on the very shutdown path the
   delegation was written to protect. The close-off task itself is
   excluded from this check because its `worktree_id` is the main
   agent's, not the target worktree's — predicate component 2 covers
   that task separately via the title match.

If ALL three hold, proceed to the delegation step below. If ANY component
fails, skip delegation and fall through to Cases A/B/C — agents that
crashed, wedged, or never produced shutdown-artifacts have nothing to
archive.

#### Delegation

Invoke the close-wave skill on this single worktree per
`plugins/cloglog/skills/close-wave/SKILL.md` **Invocation modes — Reconcile
delegation**. Close-wave accepts a worktree-name argument today, so the
call shape is:

```
close-wave(worktree="<wt-name>", invoked_from="reconcile")
```

The reconcile-invoked entry point skips user confirmation (Step 1.5),
overrides close-wave Step 4's `<wave-name>` substitution to
`reconcile-<wt-name>` (NOT a full filename — Step 4 still emits
`docs/work-logs/<date>-<wave-name>.md`, producing
`docs/work-logs/<date>-reconcile-<wt-name>.md`), and otherwise runs
Steps 2–14 unchanged. Reconcile performs no teardown steps itself for
a delegated worktree — close-wave owns the full sequence (cooperative
shutdown → shutdown-artifact consolidation → worktree/branch/tab
removal → quality gate → learnings extraction).

Record in the reconciliation report: `path: close-wave delegated
(predicate: all three components held)`. Continue to the next worktree.

#### When the predicate unexpectedly fails

A worktree that looks like Case A (`pr_merged=True`, `status=online`)
but whose predicate fails — usually because `shutdown-artifacts/work-log.md`
is missing (agent died after `mark_pr_merged` but before writing the
log) — falls through to Case A's cooperative shutdown path below. Log
each failed predicate component in the reconciliation report (e.g.
`predicate-false: missing shutdown-artifacts/work-log.md`) so we can
diagnose what broke the flow.

### Case A — PR merged, agent still registered

Same tier-1 → tier-2 path as close-wave Step 5. Snapshot the inbox offset
BEFORE the MCP call so a fast agent's `agent_unregistered` is still
observed (the race the reviewer flagged on PR #182 round 1).

```bash
SINCE_OFFSET=$(stat -c %s "$MAIN_INBOX" 2>/dev/null || echo 0)
```

1. `mcp__cloglog__request_shutdown(worktree_id)`.
2. Wait up to 120 s for `agent_unregistered` on the main inbox:
   ```bash
   uv run python "${CLAUDE_PLUGIN_ROOT}/scripts/wait_for_agent_unregistered.py" \
       --worktree "<wt-name>" \
       --inbox "$MAIN_INBOX" \
       --since-offset "$SINCE_OFFSET" \
       --timeout 120
   ```
3. On exit 0 — proceed to teardown (below).
4. On exit 1 — fall back: `mcp__cloglog__force_unregister(worktree_id)`;
   record `path: force_unregister (reconcile_pr_merged_timeout)` in the
   reconciliation report.

### Case B — Wedged agent (status=online, stale heartbeat)

Same shape as Case A but with a tighter wait — a wedged MCP call is
unlikely to recover within the full cooperative window.

```bash
SINCE_OFFSET=$(stat -c %s "$MAIN_INBOX" 2>/dev/null || echo 0)
```

1. `mcp__cloglog__request_shutdown(worktree_id)`.
2. Wait up to 30 s:
   ```bash
   uv run python "${CLAUDE_PLUGIN_ROOT}/scripts/wait_for_agent_unregistered.py" \
       --worktree "<wt-name>" \
       --inbox "$MAIN_INBOX" \
       --since-offset "$SINCE_OFFSET" \
       --timeout 30
   ```
3. On exit 0 — the agent was responsive after all; proceed to teardown.
4. On exit 1 — `mcp__cloglog__force_unregister(worktree_id)`; record
   `path: force_unregister (reconcile_wedged)` and log the stale
   `last_heartbeat` value for diagnosis.

### Case C — Orphaned worktree (no running agent)

Skip tier-1 — there is no agent to respond. If a `list_worktrees` row
exists with `status=offline`, call
`mcp__cloglog__force_unregister(worktree_id)` to ensure the row is
fully cleared (idempotent — returns `{"already_unregistered": true}`
when the row is already gone, which is also the expected shape for a
path that never had a row). Then proceed directly to teardown. No
cooperative wait, no `request_shutdown`.

### Teardown (all cases, after the agent is unregistered)

After the worktree has unregistered — by Case A/B cooperative success,
Case A/B tier-2 fallback, or Case C directly.

- **Zellij tab**: close via
  `"${CLAUDE_PLUGIN_ROOT}/hooks/lib/close-zellij-tab.sh" "<wt-name>"`.
  Never call `zellij action close-tab` directly — it takes no argument
  and closes the focused tab, which has twice been the supervisor's own
  tab (T-339). The helper refuses (exit 2) when the resolved target is
  the focused tab; on exit 2, log the refusal and skip teardown for that
  worktree this round — do NOT fall back to a bare `close-tab`.
- **Worktree path**: `git worktree remove --force <path>`. Run
  `.cloglog/on-worktree-destroy.sh` if it exists.
- **Local branch**: `git branch -D <branch>`.
- **Remote branch** (if stale per Check 4): use bot token — `git push origin --delete <branch>`.

### Stale close-off tasks (T-371)

Any backlog task whose title matches `Close worktree wt-<X>` for a `wt-<X>`
that **no longer exists** is stale: the wave's PR already merged, the
worktree was torn down, but pre-T-371 close-wave runs never moved the
close-off row through `in_progress → review → done`. The 2026-04 cohort
(T-355, T-357, T-359, T-361, T-364, T-366, T-369) prompted this rule.

For each `Close worktree wt-<X>` row in `backlog`:

1. Check whether `wt-<X>` is still active. The worktree is **gone** when:
   - `mcp__cloglog__list_worktrees` has no row whose `name == "wt-<X>"`, AND
   - `<repo_root>/.claude/worktrees/wt-<X>` does not exist on disk.

   If either check shows the worktree is alive, leave the row alone — it
   is a real pending close-off, not stale.

2. Try to recover the wave's `pr_url` so the closed-out task carries
   the same merge URL the live close-wave flow would have set in
   Step 13.5. **Do not grep merged commits by `${wt_X}`** —
   the canonical close-wave branch is `wt-close-<date>-<wave-name>`
   (`plugins/cloglog/skills/close-wave/SKILL.md` Step 10), and the
   `<wave-name>` is `wave-N` for ordinary runs and only carries the
   worktree name on the reconcile-delegated variant
   (`reconcile-<wt-name>`). Subject lines from the merging close-wave
   PR therefore mention `wt-<X>` only by coincidence (e.g. when the
   PR description happens to enumerate the worktrees being closed).
   The reliable lookup is the merged close-wave PR by title, scoped
   to recent history:

   ```bash
   # List recent close-wave PRs and look for one whose body mentions
   # this stale row's worktree name. The bot identity is required
   # here — see github-bot SKILL.md.
   GH_TOKEN="$BOT_TOKEN" gh pr list \
     --state merged \
     --search "in:title chore(close-wave)" \
     --json number,title,body,url,mergedAt --limit 50 \
     | jq -r --arg wt "$wt_X" \
         '.[] | select((.body // "") | contains($wt)) | .url' \
     | head -1
   ```

   If no matching close-wave PR is findable (the row predates the
   convention, or the wave was never PR'd — the original 7-row
   cohort), leave `pr_url` unset and rely on `skip_pr=True` for the
   review hop. The reconcile work log records the absence so the
   operator has a paper trail.

3. Move the row through to `review` and surface to the operator. Use
   `start_task` for the `backlog` → `in_progress` hop, NOT
   `update_task_status(..., "in_progress")` — `start_task`
   (`src/agent/services.py:374-398`) is the only entry point that
   enforces the one-active-task rule and writes
   `worktrees.current_task_id`. Bypassing it via `update_task_status`
   would let reconcile open a second active task on the main agent
   while the supervisor still has its own task in flight, leaving
   `current_task_id` stale and breaking every subsequent `start_task`
   guard until force-unregister.

   ```
   mcp__cloglog__start_task(task_id=<close_off_task_id>)
   mcp__cloglog__update_task_status(task_id, "review", pr_url=<url>)
   # OR, when no PR was findable in step 2:
   mcp__cloglog__update_task_status(task_id, "review", skip_pr=True)
   ```

   If `start_task` returns "agent already has active task(s)", **stop
   the cleanup of this row** and surface the conflict to the operator
   — the active task must clear (merge / drag / abandon) before
   reconcile can revive the stale close-off. Do not work around the
   guard.

   Agents cannot move tasks to `done` (the user-only-done invariant —
   `src/agent/services.py:502-508`); the row terminates at `review +
   pr_merged=True` (or `review + skip_pr=True` for the legacy cohort)
   and the operator drags the card on the board, the same single click
   they make for every other reviewed task. Surface the row in the
   reconcile work log with a one-line summary so they know where to
   look. Once T-371's close-wave wiring is live, this rule only fires
   for the existing stale cohort and never accumulates new rows.

### Other drift

- **Stale local branches without a worktree**: `git branch -d <branch>`
  (or `-D` if not merged).
- **Stale remote branches**: bot token — `git push origin --delete <branch>`.
- **Orphaned PRs**: close with bot token — `GH_TOKEN="$BOT_TOKEN" gh pr close <num> --comment "Closed by reconciliation: branch no longer exists"`.
- **Merged PR + task in review**: call `mcp__cloglog__mark_pr_merged` with
  the `task_id` to flip `pr_merged=True` (unblocks the `start_task` guard);
  then flag for user — only the user can move the task to done.
- **Pull merged changes**: always run `git fetch origin && git merge --ff-only origin/main` at the end to
  ensure local main is current. A non-fast-forward state means real divergence — investigate, do not paper over with a merge commit.

Report what was fixed and which path each worktree followed (cooperative vs
force_unregister) so the operator can tell at a glance whether any tier-2
escalations happened.

## Step 6: Unregister

After the reconciliation is complete, call `mcp__cloglog__unregister_agent` to clean up your own registration.
