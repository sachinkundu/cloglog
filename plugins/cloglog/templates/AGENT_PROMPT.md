# Worktree Agent — Workflow Template

This file is the **single source of truth for worktree-agent workflow**. It is
copied verbatim from `plugins/cloglog/templates/AGENT_PROMPT.md` into every
worktree by the `cloglog:launch` skill (Step 3). Do not hand-edit per task —
the per-task delta lives in `task.md` next to this file.

## Per-task delta — read `task.md` first

Before doing anything else, read `${WORKTREE_PATH}/task.md`. It carries:

- Task ID / Feature ID / Worktree ID (UUIDs needed for MCP calls).
- Task number, title, priority.
- Description and scope.
- Sibling-task warnings (zones owned by other in-flight worktrees).
- Residual TODOs hint from prior sessions on this worktree.
- Whether the task is no-PR-eligible is decided at runtime — see
  **Standalone no-PR tasks** below.

`<WORKTREE_PATH>` and `<PROJECT_ROOT>` referenced below are absolute paths
listed in `task.md`. Substitute them mentally — do not hand-paste them into
side notes.

## Work-Log Bootstrap

Check for prior per-task work logs in this worktree:

```
ls shutdown-artifacts/work-log-T-*.md 2>/dev/null
```

If any `work-log-T-<NNN>.md` files exist, read them all before any other
action — they carry decisions, files touched, codex review findings, and the
load-bearing **Residual TODOs / context the next task should know** section
from earlier sessions on this same worktree.

## Inbox handling

Two inbox files are involved. They are **distinct** and the distinction is
load-bearing:

- **Read:** `<WORKTREE_PATH>/.cloglog/inbox` (the worktree inbox). The
  backend webhook fan-out delivers `review_submitted`, `pr_merged`,
  `ci_failed`, and operator messages here.
- **Write:** `<PROJECT_ROOT>/.cloglog/inbox` (the project root inbox).
  Lifecycle events the supervisor must see (`agent_started`,
  `pr_merged_notification`, `agent_unregistered`, `mcp_unavailable`,
  `mcp_tool_error`) go here.

**Hand-pasting `<PROJECT_ROOT>/.cloglog/inbox` as your tail target is the
2026-04-30 bug — three agents sat idle for 25 minutes after operator retries
went to the wrong file.** Tail the **worktree** inbox; write supervisor
events to the **project root** inbox.

### Spawn one persistent inbox monitor

Persistent monitors survive `/clear`, so a naive re-spawn duplicates every
event. Reconcile against existing monitors before spawning:

1. Call `TaskList`.
2. Filter for running Monitor tasks whose `command` ends in `.cloglog/inbox`
   and resolves to **this** worktree's inbox file (path suffix
   `/.cloglog/inbox`, absolute path equal to
   `<WORKTREE_PATH>/.cloglog/inbox`).
3. Branch on the count of matches:
   - **Exactly one** → reuse it; do not spawn.
   - **Zero** → spawn a fresh persistent monitor:
     ```
     Monitor(
       command: "mkdir -p <WORKTREE_PATH>/.cloglog && touch <WORKTREE_PATH>/.cloglog/inbox && tail -n 0 -F <WORKTREE_PATH>/.cloglog/inbox",
       description: "Worktree inbox events",
       persistent: true
     )
     ```
     The `mkdir`/`touch` prelude is mandatory — the inbox is created lazily
     on first webhook write and `tail -f` against a missing file exits.
     `-n 0` starts at end-of-file (deliver only events appended from now on);
     replaying from the start re-delivers handled `pr_merged` events and
     trips the one-active-task guard. `-F` re-opens by name on rotation.
   - **Two or more** → keep the oldest matching monitor; `TaskStop` the
     rest.

## MCP tool preload

MCP tools are deferred and MUST be loaded via `ToolSearch` before calling:

```
ToolSearch(query: "select:mcp__cloglog__register_agent,mcp__cloglog__start_task,mcp__cloglog__update_task_status,mcp__cloglog__get_my_tasks,mcp__cloglog__unregister_agent,mcp__cloglog__add_task_note,mcp__cloglog__mark_pr_merged,mcp__cloglog__report_artifact,mcp__cloglog__search")
```

`mcp__cloglog__search` is in the preload so any later T-NNN/F-NN/E-N
reference resolves in one call instead of paging the board.

## Stop on MCP failure

Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating.

Per `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §4.1:

- **Startup unavailability** (ToolSearch returns no matches, or the first MCP
  call after register fails at the transport layer): write an
  `mcp_unavailable` event to `<PROJECT_ROOT>/.cloglog/inbox` and exit.
- **Runtime tool error** (MCP tool call returns 5xx, backend exception, 409
  state-machine guard, auth rejection, or schema error): write an
  `mcp_tool_error` event to `<PROJECT_ROOT>/.cloglog/inbox` carrying the
  failing tool name + error, halt, and wait on your inbox monitor for
  main-agent guidance.
- **Transient network** (`ECONNRESET`, `ETIMEDOUT`, fetch timeout): one retry
  after ≥ 2s backoff, then escalate to `mcp_tool_error` on second failure.

Never retry a 409 or a 5xx. Never fall back to direct HTTP or `gh api`.

## Standard workflow

1. Spawn the inbox monitor (see **Inbox handling** above).
2. **Register this MCP session.** The MCP server keeps `currentWorktreeId`
   and `agent_token` per-process (`mcp-server/src/server.ts:44-47`,
   `mcp-server/src/client.ts:99-105`), so the supervisor's prior
   `register_agent` call in *its* session does not populate this session's
   state — without an explicit call here, every later
   `mcp__cloglog__*` call returns `Not registered`. The supervisor's
   `register_agent` was for the **board row** (so the launch shows up
   immediately); this call is for the **MCP session** that the agent runs
   in. The backend handles re-registration idempotently — calling again
   with the same `worktree_path` returns the existing row.
   ```
   mcp__cloglog__register_agent(worktree_path=<WORKTREE_PATH from task.md>)
   ```
   Then echo `agent_started` to the project root inbox so the supervisor
   sees you live:
   ```
   printf '{"type":"agent_started","worktree":"<wt-name>","worktree_id":"<uuid>","ts":"%s"}\n' "$(date -Is)" \
     >> <PROJECT_ROOT>/.cloglog/inbox
   ```
   (`<wt-name>` and `<uuid>` come from `task.md`.)
3. **Start the task named by `task.md`.** Call `mcp__cloglog__start_task`
   with the UUID from `task.md`. The supervisor wrote `task.md` at launch
   time and is responsible for rewriting it on every continuation
   relaunch — task.md is the authoritative pointer.

   If `start_task` returns a backend error (409 because the task is
   already `done` / `review`, "Not registered", or any other 4xx/5xx),
   that is a runtime MCP tool error per `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md`
   §4.1: emit `mcp_tool_error` to the project root inbox and halt. **Do
   not** retry the call or fall back to `get_my_tasks`. A 409 specifically
   means the supervisor's `task.md` rewrite is missing or stale — the
   supervisor sees the event, re-resolves the next task, rewrites
   `task.md`, and re-issues the continuation prompt. The agent's job is
   to surface the failure crisply, not to second-guess the supervisor.

   `mcp__cloglog__get_my_tasks()` does not expose `task_type` and
   `mcp__cloglog__search` does not expose `description`
   (`src/agent/schemas.py:67-78`, `src/board/schemas.py:272-281`), so an
   agent-side fallback cannot reproduce the supervisor's pipeline-aware
   pick or refresh stale scope. Trust `task.md` and escalate on error.
4. Run the project's existing tests to establish a green baseline. Run the
   project quality gate (`make quality` for cloglog) so you know any later
   failure is your delta.
5. Implement the task per the scope in `task.md`.
6. Run the project quality gate again — it must pass.
7. Produce proof-of-work: invoke `Skill({skill: "cloglog:demo"})`. The skill
   classifies the diff and terminates in one of three states (real demo,
   committed exemption, or static auto-exempt). Do not pre-decide.
8. Open the PR via `Skill({skill: "cloglog:github-bot"})`. Every GitHub
   operation goes through the bot identity — never `git push` / `gh pr` /
   `gh api` without the bot token.
9. Move the task to review with the PR URL:
   `mcp__cloglog__update_task_status(task_id, "review", pr_url=<url>)`.
10. Your inbox monitor delivers review/merge/CI events automatically. On
    `review_submitted` from a login listed in
    `.cloglog/config.yaml: reviewer_bot_logins`, run the auto-merge gate per
    the `github-bot` skill's **Auto-Merge on Codex Pass** section. On
    `pr_merged`, run the per-task shutdown sequence below.

## Per-task shutdown sequence — `pr_merged`

1. Append a `pr_merged_notification` line to `<PROJECT_ROOT>/.cloglog/inbox`:
   ```
   printf '{"type":"pr_merged_notification","worktree":"<wt-name>","worktree_id":"<uuid>","task":"T-NNN","task_id":"<uuid>","pr":"<pr-url>","pr_number":NNN,"ts":"%s"}\n' "$(date -Is)" \
     >> <PROJECT_ROOT>/.cloglog/inbox
   ```
   (T-262 — the `pr_merged` webhook only fans out to the merging worktree's
   own inbox; the supervisor needs the explicit notification.)
2. Call `mcp__cloglog__mark_pr_merged(task_id, worktree_id)`.
3. For `spec` tasks: call
   `mcp__cloglog__report_artifact(task_id, worktree_id, artifact_path)`.
4. Write `shutdown-artifacts/work-log-T-<NNN>.md` per the schema in
   `${CLAUDE_PLUGIN_ROOT}/agents/worktree-agent.md` **Per-Task Work-Log
   Schema**. The **Residual TODOs / context the next task should know**
   section is the load-bearing handoff — write it carefully.
5. Build the aggregate `shutdown-artifacts/work-log.md` by concatenating all
   `work-log-T-*.md` files in chronological order plus a one-line envelope
   header (close-wave Step 5d depends on this aggregate).
6. **Emit `agent_unregistered` to `<PROJECT_ROOT>/.cloglog/inbox` *before*
   calling `unregister_agent`.** Shape:
   ```json
   {
     "type": "agent_unregistered",
     "worktree": "<wt-name>",
     "worktree_id": "<uuid>",
     "ts": "<utc-iso>",
     "tasks_completed": ["T-NNN"],
     "prs": {"T-NNN": "<pr-url>"},
     "artifacts": {
       "work_log": "/abs/path/shutdown-artifacts/work-log.md",
       "learnings": null
     },
     "reason": "pr_merged"
   }
   ```
   Absolute paths required. Build `prs` by calling `get_my_tasks()` and
   keying each row's `pr_url` at `T-{row.number}`; rows with null `pr_url`
   (plan tasks) are omitted. Do **not** rely on the SessionEnd hook — this
   event is authoritative.
7. Call `mcp__cloglog__unregister_agent` and exit. Do **not** call
   `get_my_tasks` to start the next task — the supervisor handles that.

## Standalone no-PR tasks (`skip_pr`)

Some tasks (docs, research, prototypes, internal-only refactors with no
user-observable surface) finish without a PR. The decision is **runtime**
— make it when you reach Standard workflow step 8 by inspecting your own
diff:

- If `git diff $(git merge-base origin/main HEAD) HEAD` shows zero changes
  to `*.py`, `*.ts`, `*.tsx`, `*.js`, `frontend/src/**`, `mcp-server/src/**`
  — the task is no-PR-eligible. Commit locally, then call
  `mcp__cloglog__update_task_status(task_id, "review", skip_pr=True)`
  instead of opening a PR.
- Otherwise the standard `pr_merged` flow applies.

When `skip_pr=True` was used the per-task shutdown sequence runs with
`reason: "no_pr_task_complete"` instead of `"pr_merged"`, skipping
`mark_pr_merged` and `pr_merged_notification`. The other steps (work log,
aggregate, emit `agent_unregistered`, unregister, exit) run unchanged.

The `skip_pr` decision is not stored on the board — the backend exposes
`skip_pr` only at `update_task_status` time
(`src/agent/schemas.py:60-65`, `mcp-server/src/tools.ts:29-35`), and there
is no persisted `workflow_override` field. Each agent decides at PR time
based on the actual diff it produced.

## One task per session

Each session ends after one PR merge (or after a `skip_pr` standalone task
completes). The supervisor sees `agent_unregistered`, checks for remaining
backlog tasks on this worktree via `get_active_tasks` filtered by
`worktree_id`, and either relaunches with the continuation prompt below or
triggers `cloglog:close-wave`.

**Plan tasks are the only exception** — a plan task (no PR, committed
locally with `skip_pr=True`) immediately starts the following impl task in
the same session. The session boundary fires when the impl task's PR
merges.

## Continuation prompt

When the supervisor relaunches this worktree for task N+1 after task N's PR
merged, it issues:

```
Read <WORKTREE_PATH>/AGENT_PROMPT.md and all shutdown-artifacts/work-log-T-*.md files in <WORKTREE_PATH>, then begin the next task.
```

The new session reads this template (already on disk), reads the prior
work logs (Work-Log Bootstrap section above), loads MCP tools, **calls
`register_agent` to bind this MCP session to the worktree** (the previous
session's `unregister_agent` cleared its registration; the MCP server's
per-process `currentWorktreeId` is gone with the prior process), then
follows Standard workflow step 3 unchanged: trust `task.md`'s UUID and
call `start_task`. If the backend returns a 4xx/5xx because `task.md` is
stale (the supervisor's `task.md` rewrite for task N+1 hasn't landed yet),
emit `mcp_tool_error` to the project root inbox and halt — the supervisor
sees the event, rewrites `task.md`, and re-issues the continuation
prompt. The continuation flow uses **the same** task-resolution contract
as initial launch; there is no second contract.

**Residual TODO — supervisor-side `task.md` rewrite.** The proper end
state has the supervisor rewrite `${WORKTREE_PATH}/task.md` before
issuing the continuation prompt (using the same Step 3 rendering shape
the launch SKILL uses on initial launch). That edit lands in the
Supervisor Relaunch Flow section, which T-356 currently owns. Until it
ships, every continuation hits the `mcp_tool_error` escalation path
above on the very first `start_task` — that is correct
fail-loud-fast behaviour. Do not paper over with an agent-side
`get_my_tasks` fallback: `TaskInfo` does not expose `task_type` so the
agent cannot reproduce the supervisor's pipeline-aware pick.
