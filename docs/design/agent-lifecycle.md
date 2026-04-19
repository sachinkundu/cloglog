# Agent Lifecycle Protocol

This document is the canonical specification for how a cloglog worktree agent
lives and dies. Every plugin skill, agent template, and `AGENT_PROMPT.md` that
touches shutdown, the inbox, or MCP discipline MUST defer to this document
rather than restate the rules inline. Where existing files disagree with this
spec, the spec wins; the disagreements are being migrated out under the
follow-up tasks listed in [See also](#see-also).

Scope: applies to every worktree-level Claude Code session launched by the
`cloglog:launch` skill. The *main* session (the registrant that launches and
supervises worktrees) follows a superset — it owns tier 2 and tier 3 shutdown
(Section 5) and never unregisters itself automatically.

Audience: agents, skill authors, and template maintainers. This is a reference
doc, not a tutorial.

## 1. Exit condition

**An agent's work is done when `get_my_tasks` returns no task in `backlog`
status for this worktree.** That is the single, authoritative exit signal.

Corollary — things that are NOT exit signals:

| Signal | Why it is not the exit signal |
| --- | --- |
| A single PR merged | The agent may have further `backlog` tasks queued. `pr_merged` only fires the "maybe start next task" flow. |
| The task shows `done` on the board | `done` is administrative and user-driven. No push notification fires when a task moves `review` → `done`. `task_status_changed` is emitted on the SSE event bus (dashboard consumer only) and never reaches the worktree inbox. An agent that waits for `done` deadlocks forever. |
| The "feature pipeline" is complete | Prior docs spoke of spec → plan → impl as the unit of completion. That concept is retired. Only `get_my_tasks` is authoritative; pipeline-level state is derived, not awaited. |

A task that is `review` with `pr_merged = True` is **finished from the agent's
side.** The task still needs a human to drag it to `done`, but the agent has no
further responsibility for it. The agent does not monitor, reply to, or block
on such tasks.

### Decision algorithm on every `pr_merged` event

```
1. mark_pr_merged(task_id, worktree_id)
2. For spec/plan tasks: report_artifact(task_id, worktree_id, artifact_path)
3. tasks = get_my_tasks()
4. next = first task in tasks with status == backlog
5. if next exists:
       start_task(next.id) and continue working
   else:
       run the Section 2 shutdown sequence
```

Step 5 has no third branch. An empty backlog means shut down — regardless of
how many `review` tasks still sit on the board with the agent's `worktree_id`
attached.

## 2. Shutdown sequence

The agent's side of shutdown runs in this order. Skip steps that do not apply
to the exiting task type, but never reorder them.

1. **`mark_pr_merged(task_id, worktree_id)`** — only if the task had a PR that
   merged and the flip has not already been applied by the webhook consumer.
   The call is idempotent; the agent makes it unconditionally as a fallback
   rather than trying to detect whether the webhook already fired.
2. **`report_artifact(task_id, worktree_id, artifact_path)`** — only for
   `task_type = spec` or `task_type = plan`. The state-machine guard blocks
   downstream tasks until this is recorded. `impl` and standalone tasks skip.
3. **Generate `shutdown-artifacts/`** inside the worktree:
   - `work-log.md` — timeline and scope of what the agent did this run.
   - `learnings.md` — patterns, gotchas, or follow-up items future agents
     should know.
   - Optional: a final state snapshot (tasks started, artifacts produced, PRs
     opened, outstanding questions) if useful to the main agent's close-wave
     step. Absolute paths to both files must be included in the
     `agent_unregistered` event in the next step.
4. **Emit `agent_unregistered` to the main agent inbox**
   (`/home/sachin/code/cloglog/.cloglog/inbox`) *before* calling
   `unregister_agent`. Shape:

   ```json
   {
     "type": "agent_unregistered",
     "worktree": "wt-...",
     "worktree_id": "<uuid>",
     "ts": "<utc-iso>",
     "tasks_completed": ["T-NNN", "T-NNN"],
     "artifacts": {
       "work_log": "/abs/path/shutdown-artifacts/work-log.md",
       "learnings": "/abs/path/shutdown-artifacts/learnings.md"
     },
     "reason": "all_assigned_tasks_complete"
   }
   ```

   This event is the trigger the main agent's close-wave flow reacts to. It is
   authoritative — the backend's `WORKTREE_OFFLINE` event is a fallback, not a
   substitute. See T-243.
5. **`unregister_agent()`** — no arguments; it authenticates with the session's
   `agent_token` and ends the active session server-side.
6. **Stop.** The Claude Code process returns control; the zellij tab stays
   open. The main agent's close-wave skill removes the tab, prunes the
   worktree, and drops the per-worktree database.

The agent MUST NOT exit — explicitly or by returning — without completing
steps 4 and 5. "Session ran out of context" is not a valid excuse: the
SessionEnd hook (`plugins/cloglog/hooks/agent-shutdown.sh`) is the backstop,
but it is best-effort and fires unreliably under `zellij action close-tab`
(tracked as T-217). Do not design workflows that rely on the backstop.

## 3. Inbox contract

Every agent monitors **exactly** `<worktree_path>/.cloglog/inbox`. The path is
always within the worktree and is always named `inbox` (no worktree-id suffix).
Canonical `Monitor` invocation:

```
Monitor(
  command: "tail -f /abs/worktree_path/.cloglog/inbox",
  description: "Inbox — messages from main agent and webhook events",
  persistent: true
)
```

**Legacy note — `/tmp/cloglog-inbox-{worktree_id}` is deprecated.** The
backend's `request_shutdown` (src/agent/services.py) still writes there as of
2026-04-19; T-215 migrates the write path to `<worktree_path>/.cloglog/inbox`.
Until T-215 merges, agents running on a worktree that might receive a
cooperative shutdown should additionally tail the legacy path as a temporary
safety net; the launch skill will remove that second monitor once T-215 ships.
This spec describes the target state.

### Events that can arrive (inbound)

Webhook and supervisor events. The agent's required response is listed.

| Event `type` | Source | Required response |
| --- | --- | --- |
| `task_assigned` | main agent (inbox write) | Call `get_my_tasks`; `start_task` on the new backlog entry per Section 1's algorithm. |
| `review_submitted` | webhook | Read review body; if `changes_requested`, move task back to `in_progress`, address, push, return to `review`. Approvals with no change are informational. |
| `review_comment` | webhook | Inline PR comment. If actionable, address it like `review_submitted`; otherwise reply via the github-bot skill's comment path. |
| `issue_comment` | webhook | Issue-style PR comment. Same rule: actionable → fix; informational → reply or ignore. |
| `ci_failed` | webhook | Follow the github-bot skill's CI recovery flow. Fix the failure, push. CI re-runs on push; next `check_run` webhook delivers the result. |
| `pr_merged` | webhook | Run the Section 1 decision algorithm. `mark_pr_merged` → `report_artifact` (if applicable) → `get_my_tasks` → `start_task` or shutdown. |
| `pr_closed` | webhook | The PR closed without merging. Stop work on this task. Do not re-open the PR. Write a note to the main inbox describing the closure and wait for guidance. |
| `shutdown` | backend (`request_shutdown`) | Finish the current MCP call, then run the full Section 2 shutdown sequence. Do not start new work. |
| `mcp_tools_updated` | main agent (T-244) | Inspect the `added`/`removed` list. If the currently active task depends on the change, emit `need_session_restart` to the main inbox, pause, wait for the main agent to close and relaunch the tab (Section 6). Otherwise continue — the current session's MCP tool list is frozen at start and cannot hot-reload. |

### Events the agent emits (outbound only)

These are produced by the agent and written to the **main** inbox
(`/home/sachin/code/cloglog/.cloglog/inbox`), never received by it.

| Event `type` | When |
| --- | --- |
| `agent_started` | Immediately after a successful `register_agent`. Tells the main agent the worktree is live. |
| `agent_unregistered` | Step 4 of the Section 2 shutdown sequence, before `unregister_agent`. Carries paths to shutdown artifacts. |
| `mcp_unavailable` | Any MCP failure (Section 4). Includes the failing tool name and error text. |
| `need_session_restart` | On `mcp_tools_updated` when the new tools are load-bearing for the active task. |

### Events that will NEVER arrive

These events live on the SSE event bus (consumed by the dashboard and the
webhook dispatcher) but are never bridged into any worktree inbox. An agent
that awaits one will deadlock.

- `task_status_changed` — including the `review` → `done` transition. This is
  the specific trap the T-225 incident hit on 2026-04-19. There is no push
  signal that a card moved to `done`; agents MUST NOT block on that state.
- Any other board-mutation event (`task_moved`, `feature_created`,
  `epic_updated`, etc.) — all are SSE-only.
- `worktree_offline` — that event exists server-side for dashboard and
  supervisor consumers but is never written to the target worktree's own
  inbox (it cannot be; by the time it fires the agent's session is gone).

If an AGENT_PROMPT, skill, or template tells an agent to "wait for the task to
show done" or "block on the board showing merged," the prompt is wrong and
must be fixed.

## 4. MCP discipline

**Agents talk to the backend only through MCP tools.** No direct HTTP to
`127.0.0.1`, `localhost`, `0.0.0.0`, an IPv6 literal, or the cloudflared tunnel
hostname. No `curl`, `wget`, `httpie`, `python -c 'urllib...'`, `node -e
'fetch(...)'`. No `gh api` against the backend. The project API key may be
present in the worktree environment; agents MUST ignore it (T-214 is the
follow-up that removes it from the worktree entirely).

An **MCP failure** is ANY of:

- `ToolSearch` returns no matches for an `mcp__cloglog__*` tool (load failure).
- An MCP tool call returns an error: fetch error, HTTP 5xx, auth rejection,
  timeout, schema validation error, malformed response.

Required response to any MCP failure:

1. **Halt.** Do not retry the same call in a loop; do not fall back to direct
   HTTP; do not skip the operation and continue.
2. **Emit `mcp_unavailable` to the main inbox**
   (`/home/sachin/code/cloglog/.cloglog/inbox`):

   ```json
   {
     "type": "mcp_unavailable",
     "worktree": "wt-...",
     "tool": "mcp__cloglog__<name>",
     "error": "<concise error text>",
     "ts": "<utc-iso>"
   }
   ```
3. **Wait** for the main agent's guidance. The main agent may repair MCP and
   signal resume, or may decide to force-unregister and reassign.

Enforcement is in the `plugins/cloglog/hooks/prefer-mcp.sh` pre-bash hook. This
document is the rule that hook enforces; see T-219 for the hook hardening that
closes current bypass holes.

## 5. Three-tier shutdown from the main side

The main agent has three mechanisms for ending a worktree session. They are
tried in order; later tiers are last resorts.

### Tier 1 — Cooperative shutdown (`request_shutdown`)

- **Invocation.** Main calls `mcp__cloglog__request_shutdown(worktree_id)` (the
  MCP tool tracked as T-218; the backend endpoint already exists at
  `POST /agents/{worktree_id}/request-shutdown`).
- **Effect.** The backend writes a `{"type":"shutdown"}` JSON line to
  `<worktree_path>/.cloglog/inbox` (target state post-T-215). The agent's
  `Monitor` delivers the event in under a second; the agent runs the full
  Section 2 sequence and stops.
- **Success signal.** Main waits for an `agent_unregistered` line in its own
  inbox (primary) and polls the worktree row's status (secondary).
- **Concrete numbers (proposed target for T-220).**
  - Cooperative timeout: **120 s** from `request_shutdown` to `agent_unregistered`.
  - Poll interval on the worktree row: **10 s**.
  - Retries of `request_shutdown` itself: **1** if the first call did not
    produce a `shutdown` line in the worktree inbox within 10 s — suggests the
    inbox write failed, not that the agent is ignoring it.
- **When to use.** Always first. Preserves shutdown-artifacts, learnings, and
  a clean `unregister` row. It is the only tier that yields a usable work log.

### Tier 2 — Force unregister (`force_unregister`)

- **Invocation.** Main calls `mcp__cloglog__force_unregister(worktree_id)` (T-221
  admin tool; authenticates with the project API key, NOT the agent token, so
  it works when the agent is unreachable).
- **Effect.** Backend marks the worktree unregistered unconditionally, ends any
  active session row, and emits `WORKTREE_OFFLINE` with reason
  `force_unregistered`. The agent's Claude Code process is NOT killed — it
  merely loses its backend session. If the agent is still running, its next
  MCP call will fail with auth rejection; the agent then follows Section 4 and
  writes `mcp_unavailable` to the main inbox, which main can ignore.
- **When to use.** After tier 1's 120 s timeout elapses without an
  `agent_unregistered` event, OR when the agent is known wedged (process
  looping, MCP call stuck, terminal unresponsive) and cooperative shutdown has
  no chance of succeeding.
- **Cost.** State loss. Shutdown-artifacts may be absent or partial; the
  `work-log` and `learnings` files must be reconstructed by the main agent
  from the board, PRs, and commits. The reconcile/close-wave rewrite (T-220)
  is responsible for the best-effort reconstruction.

### Tier 3 — Heartbeat timeout (server-side sweep)

- **Mechanism.** `src/agent/scheduler.py` runs `check_heartbeat_timeouts` every
  **60 s**. Sessions with `last_heartbeat` older than **180 s** (the
  `heartbeat_timeout_seconds` setting in `src/shared/config.py`) are marked
  timed out; backend emits `WORKTREE_OFFLINE` with reason `heartbeat_timeout`.
- **When it fires.** The agent died (process killed, machine rebooted, network
  partition) without issuing tier 1 or tier 2 explicitly. It is the catch-all,
  not a cooperative signal.
- **Main-agent action.** Treat a `WORKTREE_OFFLINE{reason:heartbeat_timeout}`
  on the dashboard or supervisor stream the same as a tier 2 force — no
  clean artifacts; reconstruct from PRs/commits.

### Escalation matrix

```
t = 0   : main calls request_shutdown (tier 1)
t + 10s : if no shutdown line in worktree inbox, retry request_shutdown once
t + 120s: if no agent_unregistered in main inbox, call force_unregister (tier 2)
t + *   : if neither tier 1 nor tier 2 was reached (main agent itself is down),
          server sweep closes the session after 180 s of silence (tier 3)
```

Timeouts marked "proposed target for T-220" are the recommended numbers for
the close-wave/reconcile rewrite. Current close-wave does not ask; it rips
tabs down without tier 1 at all. See T-220.

## 6. Agent session can't self-exit and relaunch

A Claude Code session is one process; it cannot restart itself. Specifically:

1. **`/exit` or the model ending the turn returns control to the shell.** The
   bash parent is the `launch.sh` script the cloglog launch skill wrote:

   ```bash
   #!/bin/bash
   cd "${WORKTREE_PATH}"
   exec claude --dangerously-skip-permissions 'Read AGENT_PROMPT.md and begin.'
   ```

   `exec claude` replaces the shell; when claude exits, the process tree ends.
   The zellij pane keeps displaying the last frame of output but has no
   running process. Verified 2026-04-19.
2. **There is no wrapper loop.** `launch.sh` is not `while true; do claude ...;
   done`. That was considered and rejected — it would mask crash loops and
   hide state that the main agent needs to observe.
3. **Therefore "exit so your tab relaunches" is impossible.** Any prompt,
   skill, or template that tells an agent to exit and expect a fresh session
   is broken and must be fixed. The same applies to the
   `mcp_tools_updated` broadcast (T-244): an agent that needs new MCP tools
   CANNOT pick them up by exiting.

### Restart-for-new-tools protocol (target state, pending T-244)

1. Main-agent post-merge hook rebuilds `mcp-server/dist/` after any merge that
   touched `mcp-server/src/**`.
2. Main broadcasts an `mcp_tools_updated` event to every active worktree's
   `.cloglog/inbox`:

   ```json
   {"type":"mcp_tools_updated","added":["new_tool_a"],"removed":[],"ts":"..."}
   ```
3. A worktree agent that needs the new tools emits `need_session_restart` to
   the main inbox and pauses (no new MCP calls, no new commits).
4. Main closes the worktree's zellij tab and opens a new one via the launch
   skill; the new Claude session loads the updated MCP tool list at startup.
5. The agent resumes its active task via `register_agent` (the register is
   idempotent; it returns the existing session) and continues.

An agent that receives `mcp_tools_updated` but does NOT need the change keeps
working as normal — no restart, no pause.

## See also

Follow-up tasks that carry out the migration this spec describes. Each is a
separate board task under F-48 (Agent Lifecycle Hardening — Graceful Shutdown
& MCP Discipline). Link here as they land:

- **T-215** — Unify shutdown inbox path: backend `request_shutdown` writes to
  `<worktree_path>/.cloglog/inbox` instead of `/tmp/cloglog-inbox-{id}`.
- **T-216** — Sync plugin docs/skills to the unified inbox path. Audit pass
  against `worktree-agent.md`, `claude-md-fragment.md`, `github-bot/SKILL.md`,
  and `launch/SKILL.md`.
- **T-217** — SessionEnd shutdown hook fires reliably on
  `zellij action close-tab` (currently drops under SIGKILL).
- **T-218** — Add the `request_shutdown` MCP tool wrapping the existing
  backend endpoint.
- **T-219** — Harden `prefer-mcp.sh` to close the `127.0.0.1` / keyword-allowlist
  bypasses and broaden the rule from load-time to runtime MCP failures.
- **T-220** — Rewrite `reconcile` and `close-wave` skills to use the Section 5
  three-tier shutdown flow. Uses the concrete numbers in Section 5 as its
  target. Depends on T-218 and T-221.
- **T-221** — Admin `force_unregister`: backend endpoint (project-scoped auth)
  plus MCP tool for tier 2.
- **T-243** — Enforce the `agent_unregistered` inbox event in the agent
  shutdown path and the SessionEnd hook backstop.
- **T-244** — Post-merge mcp-server dist rebuild + `mcp_tools_updated`
  broadcast. Implements Section 6's restart-for-new-tools protocol.

### Callers to audit during T-216

The T-216 audit pass covers `worktree-agent.md`, `claude-md-fragment.md`,
`github-bot/SKILL.md`, and `launch/SKILL.md`. Specific lines found to
contradict this spec while writing it:

- `plugins/cloglog/agents/worktree-agent.md:32–36, 49–52, 76–79` — mandates
  `/loop 5m` polling as "not optional." This spec says the inbox Monitor is
  the single delivery channel; `/loop` is forbidden after PR creation.
- `plugins/cloglog/agents/worktree-agent.md:133, 139` — Monitor and send-to-agent
  examples use `/tmp/cloglog-inbox-{worktree_id}`. T-215/T-216 migrate to
  `<worktree_path>/.cloglog/inbox`.
- `plugins/cloglog/agents/worktree-agent.md:155–163` — shutdown trigger is
  framed as "get_my_tasks returns empty AND the feature pipeline is complete."
  This spec drops the pipeline conjunct entirely (Section 1).
- `plugins/cloglog/templates/claude-md-fragment.md:55` — tier 2 of the
  three-tier shutdown is `SIGTERM`. This spec replaces it with
  `force_unregister` (Section 5 / T-221).
- `plugins/cloglog/templates/claude-md-fragment.md:70–73` — "Agent
  Communication" block uses the `/tmp/cloglog-inbox-{id}` path.
- `plugins/cloglog/skills/launch/SKILL.md:93–105` — embedded agent prompt
  workflow has step 12 ("Poll for comments and merge") and two steps both
  numbered 13; the second omits `mark_pr_merged` and `report_artifact`. The
  template should reference this spec instead of restating the flow.
