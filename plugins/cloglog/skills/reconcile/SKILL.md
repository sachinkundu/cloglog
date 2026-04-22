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

### Check 2: Tasks with merged PRs still attached to a worktree

Use `mcp__cloglog__get_board`. `TaskCard` carries `status`, `pr_url`,
`pr_merged`, and `worktree_id` (see `src/board/schemas.py` —
`TaskResponse` → `TaskCard`). It does **not** carry worktree
`status`/`last_heartbeat`/`worktree_path` — those live on
`WorktreeResponse` at `/projects/{project_id}/worktrees`, which is not
currently exposed via MCP (tracked as a follow-up — see the *Known gaps*
block below).

Given the available data, the automatable drift class is:

- **`pr_merged_still_registered`** — task has `pr_merged=True`, `status=review`,
  and a non-null `worktree_id`. The agent should have unregistered on the
  `pr_merged` webhook (§2) but did not. Auto-fix: Case A.

### Check 3: Project-local worktree inventory

Run `git worktree list --porcelain` and **filter to only worktrees whose
path starts with the project root's `.claude/worktrees/` directory**.
This is for the project-scope guardrail (never touch worktrees owned by
claude-squad, vibe-kanban, a sibling project, etc.), not for classifying
drift cases on its own. The project root is the parent of
`--git-common-dir`:

```bash
PROJECT_ROOT="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
```

For each in-scope worktree, check whether its branch is fully merged into
main (`git branch --merged main | grep <branch>`); a merged branch with
no associated active task is stale.

**Never touch worktrees outside your project's directory.** Other tools
manage their own worktrees.

### Known gaps — wedged-agent and orphaned-worktree detection

The deliverables for this skill list two additional drift classes that
the current MCP tool surface cannot detect on its own:

- **Wedged agent** — registered, but not heartbeating / task stuck in
  `in_progress`. Requires `last_heartbeat` and worktree `status` from
  `WorktreeResponse`, currently only returned by the REST endpoint
  `GET /projects/{project_id}/worktrees`. Add a `list_worktrees` MCP
  tool (follow-up task) and then Case B becomes derivable here.
- **Orphaned worktree** — filesystem worktree path exists under
  `.claude/worktrees/` with no registered agent. `get_board` maps tasks
  to `worktree_id`, not paths, so the same `list_worktrees` tool is what
  closes this gap. Once it lands, Case C becomes `force_unregister` by
  worktree_id resolved from path.

Until the follow-up lands, the supervisor handles wedged/orphaned
cases manually (cooperative shutdown if the agent is reachable;
`force_unregister(worktree_id)` once the UUID is known from the
agent_started inbox event).

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

### Case A — PR merged, agent still registered

Same tier-1 → tier-2 path as close-wave Step 5. Snapshot the inbox offset
BEFORE the MCP call so a fast agent's `agent_unregistered` is still
observed (the race the reviewer flagged on PR #182).

```bash
SINCE_OFFSET=$(stat -c %s "$MAIN_INBOX" 2>/dev/null || echo 0)
```

1. `mcp__cloglog__request_shutdown(worktree_id)`.
2. Wait up to 120 s for `agent_unregistered` on the main inbox:
   ```bash
   uv run python scripts/wait_for_agent_unregistered.py \
       --worktree "<wt-name>" \
       --inbox "$MAIN_INBOX" \
       --since-offset "$SINCE_OFFSET" \
       --timeout 120
   ```
3. On exit 0 — proceed to teardown (below).
4. On exit 1 — fall back: `mcp__cloglog__force_unregister(worktree_id)`;
   record `path: force_unregister (reconcile_pr_merged_timeout)` in the
   reconciliation report.

### Teardown (Case A, after the agent is unregistered)

Only after the worktree has unregistered — by Case A success OR Case A
tier-2 fallback.

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
