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

### Decision algorithm

The algorithm fires at each of two triggers:

- **Trigger A — `pr_merged` inbox event.** Used by tasks with a PR (spec, impl,
  standalone-with-code).
- **Trigger B — local commit of the artifact is done.** Used by tasks with NO
  PR (plan tasks, and any docs/research task that finishes without opening a
  PR). The agent itself decides when to run this trigger; there is no
  webhook.

```
on trigger A (pr_merged):
    0. emit pr_merged_notification to <project_root>/.cloglog/inbox
       (T-262: surfaces the merge to the supervisor's inbox so a parallel
       worktree blocked on this PR sees the unblock without polling
       gh pr list. Carries worktree, worktree_id, task, task_id, pr,
       pr_number, ts.)
    1. mark_pr_merged(task_id, worktree_id)
    2. if task_type in (spec, plan):
           report_artifact(task_id, worktree_id, artifact_path)

on trigger B (no-PR task finished):
    1. update_task_status(task_id, "review", skip_pr=True)
    2. if task_type in (spec, plan):
           report_artifact(task_id, worktree_id, artifact_path)

continuation (both triggers):
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

**Note on the plan-task path.** Trigger B assumes the agent can move to
`review` without a PR. The backend today accepts that via `skip_pr=True` in
`update_task_status`, and `report_artifact` only requires the task be in
`review` (see `src/agent/services.py:516`). However, the pipeline guard's
"predecessor resolved" check still requires `pr_url` to be set
(`src/agent/services.py:237`), which an impl task cannot satisfy if its plan
predecessor used `skip_pr=True`. That is a backend gap; the canonical flow
here is the target state. See the T-NEW follow-up in the [See also](#see-also)
block.

## 2. Shutdown sequence

The agent's side of shutdown runs in this order. Skip steps that do not apply
to the exiting task type, but never reorder them.

1. **`mark_pr_merged(task_id, worktree_id)`** — only if the task had a PR that
   merged. Skip for plan tasks and any other no-PR task. The call is
   idempotent; for tasks that had a PR the agent makes it unconditionally as a
   fallback, rather than trying to detect whether the webhook consumer already
   flipped the flag.
2. **Move to `review` if not already there.** For spec/impl tasks with a PR
   this already happened when the PR was opened. For no-PR tasks (plan,
   docs-only), call `update_task_status(task_id, "review", skip_pr=True)`
   here. Required so the next step can accept the artifact.
3. **`report_artifact(task_id, worktree_id, artifact_path)`** — only for
   `task_type = spec` or `task_type = plan`. The state-machine guard blocks
   downstream tasks until this is recorded. `impl` and standalone tasks skip.
   Backend enforces `task.status == "review"` at this step
   (`src/agent/services.py:516`); step 2 is what guarantees it.
4. **Generate `shutdown-artifacts/`** inside the worktree:
   - `work-log.md` — timeline and scope of what the agent did this run.
   - `learnings.md` — patterns, gotchas, or follow-up items future agents
     should know.
   - Optional: a final state snapshot (tasks started, artifacts produced, PRs
     opened, outstanding questions) if useful to the main agent's close-wave
     step. Absolute paths to both files must be included in the
     `agent_unregistered` event in the next step.

   Agents generate these files from scratch every shutdown. The worktree
   bootstrap (`.cloglog/on-worktree-create.sh`) removes any inherited
   content at worktree-create time (T-242), so the directory is reliably
   empty on first boot — no template seeding is expected.
5. **Emit `agent_unregistered` to the main agent inbox**
   (`<project_root>/.cloglog/inbox` — see [Paths and discovery](#paths-and-discovery)
   in Section 3) *before* calling `unregister_agent`. Shape:

   ```json
   {
     "type": "agent_unregistered",
     "worktree": "wt-...",
     "worktree_id": "<uuid>",
     "ts": "<utc-iso>",
     "tasks_completed": ["T-NNN", "T-NNN"],
     "prs": {
       "T-NNN": "https://github.com/<org>/<repo>/pull/<n>",
       "T-NNN": "https://github.com/<org>/<repo>/pull/<n>"
     },
     "artifacts": {
       "work_log": "/abs/path/shutdown-artifacts/work-log.md",
       "learnings": "/abs/path/shutdown-artifacts/learnings.md"
     },
     "reason": "all_assigned_tasks_complete"
   }
   ```

   The `artifacts.work_log` and `artifacts.learnings` values **must be absolute paths**, not worktree-relative — the main agent reads them after the worktree is torn down and the relative root is gone by then.

   **`prs` shape (T-262, Option A — parallel map).** Keys are the same `T-NNN` strings present in `tasks_completed`; values are the GitHub PR URL the agent provided to `update_task_status(..., pr_url=...)` for that task. `tasks_completed` stays a flat list of IDs so existing parsers keep working unchanged — `prs` is purely additive. Tasks completed without a PR (plan tasks via `skip_pr=True`, or any other no-PR path) MUST be omitted from `prs` rather than mapped to `null` or an empty string. The agent builds the map by walking `get_my_tasks()` at shutdown; the `TaskInfo` response (`src/agent/schemas.py:TaskInfo`) exposes both `number` (the integer suffix) and `pr_url`, so the agent keys the map at `f"T-{row.number}"` for each row whose `pr_url` is non-null. The hook backstop emits `prs: {}` when it cannot recover the map — see Hook backstop below.

   This event is the trigger the main agent's close-wave and reconcile
   flows react to. It is authoritative — the backend's `WORKTREE_OFFLINE`
   event is a fallback, not a substitute. See T-243 for the producer side
   and T-220 for the consumer side.

   **Consumer wiring (T-220).** `plugins/cloglog/skills/close-wave/SKILL.md`
   Step 5 and `plugins/cloglog/skills/reconcile/SKILL.md` Step 5 both
   capture the supervisor inbox's byte offset BEFORE issuing
   `mcp__cloglog__request_shutdown`, then invoke
   `scripts/wait_for_agent_unregistered.py --since-offset $SINCE_OFFSET`
   against that inbox. Capturing the offset before the MCP call binds
   the wait window to "events produced in response to THIS shutdown
   request" without dropping a fast agent's `agent_unregistered` that
   lands between the MCP call returning and the helper starting
   (`tests/test_wait_for_agent_unregistered.py` pins both the
   race-is-closed invariant and the offset-filters-stale-events
   invariant). The supervisor inbox is resolved via
   `dirname "$(git rev-parse --path-format=absolute --git-common-dir)"`,
   never `git rev-parse --show-toplevel` — the latter returns the
   worktree path when the supervisor runs inside a worktree.

   **Hook backstop (T-243, T-262).** `plugins/cloglog/hooks/agent-shutdown.sh`
   writes the event as well, with `reason: "best_effort_backstop_from_session_end_hook"`
   and `worktree_id` omitted (the hook has no access to the UUID — it lives in
   backend state). The hook recovers the `prs` map via a single
   `gh pr list --state merged --head <wt-name>` call, intersected with the
   `T-NNN` IDs scanned out of merged-PR titles/bodies; if `gh` is missing,
   unauthenticated, or returns no merged PRs, the hook emits `prs: {}`
   (advisory absence — supervisors fall back to `gh pr list` lookups).
   Close-wave's consumer deduplicates on `(worktree, ts)`,
   not `(worktree_id, ts)`, and prefers the richer agent-written record when
   both are present. The backstop exists because `zellij action close-tab`
   has historically skipped the hook (T-217) — but under the cooperative
   flow the tab is closed ONLY after `unregister_agent` has returned, so
   the hook rarely fires in practice. The backstop remains defensive for
   the tier-2 force_unregister path.
6. **`unregister_agent()`** — no arguments; it authenticates with the session's
   `agent_token` and ends the active session server-side.
7. **Stop.** The Claude Code process returns control; the zellij tab stays
   open. The main agent's close-wave skill removes the tab, prunes the
   worktree, and drops the per-worktree database.

The agent MUST NOT exit — explicitly or by returning — without completing
steps 5 and 6. "Session ran out of context" is not a valid excuse: the
SessionEnd hook (`plugins/cloglog/hooks/agent-shutdown.sh`) is the backstop,
but it is best-effort and fires unreliably under `zellij action close-tab`
(tracked as T-217). Do not design workflows that rely on the backstop.

## 3. Inbox contract

### Paths and discovery

Two inbox files exist and they live in different trees. Nothing hardcodes an
absolute path; both are resolved relative to a directory the process knows at
startup.

| Inbox | Path | Resolver |
| --- | --- | --- |
| Worktree inbox (each worker) | `<worktree_path>/.cloglog/inbox` | `worktree_path` is the `path` column on the `worktrees` row for the session. The webhook consumer at `src/gateway/webhook_consumers.py` reads it directly from the row. Agents get the same path from `register_agent`'s return value and from `pwd` at startup (the launch skill's `launch.sh` always `cd`s into the worktree first). |
| Main agent inbox (supervisor) | `<project_root>/.cloglog/inbox` | `<project_root>` is the directory where `cloglog:setup` was run — the top-level clone, NOT a worktree subdirectory. `plugins/cloglog/hooks/session-bootstrap.sh` creates the file at `${PROJECT_DIR}/.cloglog/inbox` when the supervisor session starts, and `plugins/cloglog/skills/setup/SKILL.md` tells the supervisor to `tail -f <cwd>/.cloglog/inbox`. An alt-checkout at (say) `/home/sachin/code/cloglog-prod` has its supervisor inbox at `/home/sachin/code/cloglog-prod/.cloglog/inbox`. |

**Worktree agents must not hardcode the main inbox path.** The launch skill
is responsible for plumbing the project root into the worktree environment —
the target is an env var (name TBD, proposal: `CLOGLOG_PROJECT_ROOT`) exported
by `launch.sh` before `exec claude`. Until that lands, an agent can compute
it as `$(git rev-parse --path-format=absolute --git-common-dir)` then the
parent directory of `.git` (for a non-worktree clone, `--show-toplevel` also
works; for a worktree, `--git-common-dir` points at the main clone's `.git`).
Agents MUST NOT resolve it to a literal like
`/home/sachin/code/cloglog/.cloglog/inbox` — different checkouts use
different roots and the hardcode corrupts them. Tracked as T-NEW in the
[See also](#see-also) block.

Every agent monitors **exactly** `<worktree_path>/.cloglog/inbox`. The path is
always within the worktree and is always named `inbox` (no worktree-id suffix).
**Exactly one** Monitor per agent process — see the dedupe procedure in
`plugins/cloglog/skills/setup/SKILL.md` and `plugins/cloglog/skills/launch/SKILL.md`
that reconciles via `TaskList` before spawning, since persistent monitors
survive `/clear`. Canonical `Monitor` invocation (note the `mkdir`/`touch`
prelude — the inbox is created lazily by the backend's first webhook write,
and `tail -f` against a missing file exits immediately; `-n 0 -F` starts at
end-of-file and only delivers events appended from now on, which is the
correct semantic given that the inbox is **append-only for the worktree's
lifetime** — re-delivering historical events would re-process already-handled
`pr_merged`/`review_submitted` lines and trip `start_task`'s one-active-task
guard at `src/agent/services.py:357-370`. To reconcile events that landed
while the agent was offline, use the *Check PR Status* drill-down in
`plugins/cloglog/skills/github-bot/SKILL.md`, not `tail` history. `-F`
re-opens the file by name if it is rotated):

```
Monitor(
  command: "mkdir -p <worktree_path>/.cloglog && touch <worktree_path>/.cloglog/inbox && tail -n 0 -F <worktree_path>/.cloglog/inbox",
  description: "Inbox — messages from main agent and webhook events",
  persistent: true
)
```

**Legacy note — `/tmp/cloglog-inbox-{worktree_id}` is removed.** T-215 migrated
the backend's `request_shutdown` write to `<worktree_path>/.cloglog/inbox` —
the same file the webhook consumer writes to and the worktree agent tails.
There is no longer a legacy path to also monitor; the single inbox above is
authoritative for every inbound event, cooperative shutdown included.

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
(`<project_root>/.cloglog/inbox` — see [Paths and discovery](#paths-and-discovery)),
never received by it.

| Event `type` | When |
| --- | --- |
| `agent_started` | Immediately after a successful `register_agent`. Tells the main agent the worktree is live. |
| `pr_merged_notification` | On receipt of a `pr_merged` inbox event, BEFORE `mark_pr_merged`. Carries `worktree`, `worktree_id`, `task` (T-NNN string), `task_id` (UUID), `pr` (URL), `pr_number` (int), `ts`. T-262: the `pr_merged` webhook fan-out only reaches the agent's own inbox; this event surfaces the merge to the supervisor so a parallel worktree blocked on the PR can be unblocked without `gh pr list` polling. |
| `agent_unregistered` | Step 5 of the Section 2 shutdown sequence, before `unregister_agent`. Carries paths to shutdown artifacts and the `prs` map (T-262). |
| `mcp_unavailable` | **Startup** MCP failure only (Section 4.1): ToolSearch returns no matches, or the first MCP call fails at the transport layer. Agent emits and exits. |
| `mcp_tool_error` | **Runtime** MCP failure (Section 4.1): an MCP tool call returned a 5xx, a backend exception, a 409 state-machine guard, or — after one backoff retry — a transient network error. Agent emits and waits for main. |
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

### 4.1 Halt on any MCP failure

Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating.

The rule applies at two moments in a session's life, each with its own
response. An "MCP failure" never means "try something else" — the only
two outcomes are (a) halt and exit after emitting `mcp_unavailable`, or
(b) halt and wait after emitting `mcp_tool_error`. Silent continuation
is never acceptable: a 409 guard, a 5xx, or an auth rejection is the
backend telling the agent "you are wrong about board state"; proceeding
anyway ships broken work.

#### Startup unavailability → `mcp_unavailable`

Triggers:

- `ToolSearch` returns no matches for an `mcp__cloglog__*` tool (the MCP
  server did not load, or the worktree's `.mcp.json` was never generated).
- First MCP call after registration fails with a transport-level error
  (`ECONNREFUSED`, DNS failure, TLS handshake error).

Response:

1. Do not register with the board (or, if already registered, skip every
   subsequent MCP call).
2. Write `mcp_unavailable` to the main inbox
   (`<project_root>/.cloglog/inbox` — see [Paths and discovery](#paths-and-discovery)):

   ```json
   {
     "type": "mcp_unavailable",
     "worktree": "<wt-name>",
     "worktree_id": "<uuid|null>",
     "ts": "<utc-iso>",
     "tool": "mcp__cloglog__<name>|ToolSearch",
     "error": "<concise error text>",
     "reason": "startup_unavailable"
   }
   ```
3. Exit. The agent cannot participate in the board without MCP; waiting does
   not help because the session itself cannot hot-reload tools (Section 6).
   The main agent will force-unregister and re-launch after repairing MCP.

#### Runtime tool error → `mcp_tool_error`

Triggers (every one of these is the backend speaking — trust it):

- HTTP 5xx from an MCP tool call.
- Backend exception surfaced as a non-2xx error body.
- Pipeline / state-machine guard (typically HTTP 409) — e.g.,
  `start_task` returning 409 because the predecessor is not resolved,
  `update_task_status` rejecting a disallowed column transition,
  `mark_pr_merged` returning 409 because the task is not in `review`.
- Auth rejection after a successful register (usually tier-2 force-unregister
  — Section 5).
- Schema-validation error, malformed response body, unknown tool error.

Response:

1. **Halt the current task.** Do not retry the same call; do not fall back to
   direct HTTP or `gh api`; do not skip the step and "press on." A 409 is
   not advisory — the backend is refusing the transition.
2. Write `mcp_tool_error` to the main inbox:

   ```json
   {
     "type": "mcp_tool_error",
     "worktree": "<wt-name>",
     "worktree_id": "<uuid>",
     "ts": "<utc-iso>",
     "tool": "<mcp_tool_name>",
     "error": "<short message or status>",
     "task_id": "<uuid|null>",
     "reason": "runtime_tool_error"
   }
   ```

   The `reason` field is an open enum. The default is `runtime_tool_error`;
   use a more specific value when the agent recognises the error as a
   known-classifiable case so the supervisor can auto-handle without
   inspecting the error text. Recognised values today:

   | `reason` | When | Supervisor response |
   | --- | --- | --- |
   | `runtime_tool_error` | Default — any 5xx, schema error, auth rejection, unrecognised 409, retry-exhausted transient. | Diagnose from `tool` + `error`; usually a code or state fix followed by an inbox write telling the agent to resume. |
   | `pipeline_guard_blocked` | 409 from `start_task` on an impl task when the plan predecessor is in `review` with no `pr_url` (T-NEW-b backend gap). Agents MAY add a `predecessor_task_id` field carrying the blocking plan task's UUID. | Advance the impl task directly (bypass the guard) or wait for T-NEW-b to ship; then write a resume message to the worktree inbox. |

3. **Wait** on the inbox Monitor for main-agent guidance. Main may repair the
   board state (e.g., advance the pipeline so a blocked `start_task` now
   succeeds) and signal resume via a message, or may decide to
   force-unregister and reassign. Do not unregister voluntarily — the main
   agent owns the decision.

#### Transient network retry

A small class of failures is known-transient and warrants exactly one retry
before escalating:

- `ECONNRESET`, `ETIMEDOUT`, `EAI_AGAIN` on an MCP tool call that previously
  succeeded in this session.
- A fetch timeout below the tool's default deadline.

Retry policy: one attempt after a short backoff (≥ 2 s, ≤ 10 s). If the retry
also fails, treat the second failure as a **runtime tool error** and follow
the response above — emit `mcp_tool_error` and wait. Never enter a retry loop;
"two tries then escalate" is the whole policy.

HTTP 5xx and 409 are NOT transient. A 500 means the backend hit an exception;
a 409 means the backend is refusing on purpose. Neither improves by retrying.

Enforcement is in the `plugins/cloglog/hooks/prefer-mcp.sh` pre-bash hook.
This document is the rule that hook enforces; see T-219 for the hook
hardening that closes current bypass holes and extends enforcement from
startup-only to runtime tool errors.

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
  inbox (primary, scripted by `scripts/wait_for_agent_unregistered.py`) and
  optionally polls the worktree row's status as a secondary check.
- **Concrete numbers.**
  - Cooperative timeout: **120 s** from `request_shutdown` to
    `agent_unregistered`. Close-wave (Step 5b) and reconcile Case A use
    this.
  - The helper's `--poll-interval` defaults to 1 s — tight enough that a
    responsive agent's `agent_unregistered` is observed within ~1 s of
    being written.
  - The supervisor MUST capture the inbox byte offset BEFORE the
    `request_shutdown` MCP call and pass it to the helper as
    `--since-offset`. Without that, a fast agent's `agent_unregistered`
    that lands between the MCP call returning and the helper starting
    would be ignored (the race caught by the PR #182 review).
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
  MCP call will fail with auth rejection; the agent then follows Section 4.1
  (runtime tool error) and writes `mcp_tool_error` to the main inbox, which
  main can ignore (it initiated the force).
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
t + 120s: if no agent_unregistered in main inbox, call force_unregister (tier 2)
t + *   : if neither tier 1 nor tier 2 was reached (main agent itself is down),
          server sweep closes the session after 180 s of silence (tier 3)
```

Close-wave and reconcile both drive this escalation via
`scripts/wait_for_agent_unregistered.py`; see the Step 5 blocks in the
respective skills for the concrete command invocations.

### 5.5 Teardown ownership — unified flow (T-270)

The three tiers above cover the *session side* of shutdown: ending the
backend row and flushing the agent's last MCP calls. Teardown — removing
the worktree path, deleting the branch, closing the zellij tab, archiving
`shutdown-artifacts/` into `docs/work-logs/`, and folding learnings into
CLAUDE.md — is a separate concern with a single ownership rule:

> **Reconcile is the arbiter. Close-wave is the clean path.
> `force_unregister` is the dirty path.**

Two code paths used to claim teardown ownership and they disagreed on
what teardown meant:

- **close-wave** treats teardown as the *final* step of a pipeline that
  first archives `shutdown-artifacts/{work-log,learnings}.md` into
  `docs/work-logs/`, runs pr-postprocessor to fold lessons into
  CLAUDE.md, files follow-up tasks, and opens a close-off PR.
- **reconcile** treated teardown as a *direct* action: Case A / Case C
  would `git worktree remove --force` the path, and the artifacts would
  vaporize before close-wave ever saw them.

Observed on 2026-04-23 during the T-268 close-out — reconcile ran first,
the artifacts were destroyed, and the auto-filed close-off task could
not complete its archive steps. T-270 resolves the split-brain:

1. **Reconcile's Step 5.0 now gates Case A / Case C on a
   "completed-cleanly" predicate** — `shutdown-artifacts/work-log.md`
   exists, a `Close worktree <wt-name>` task exists in `backlog`, and
   every assigned task is resolved from the agent's side. "Resolved"
   means `status == "done"`, OR `status == "review"` with
   `pr_merged == True`, OR `status == "review"` with `pr_url is None`
   (the no-PR task path via `skip_pr=True` per §1 Trigger B) — the
   same set `close_worktree_template` uses at `src/board/templates.py:24-25`.
   A stricter "`pr_merged=True` everywhere" reading would falsely
   reject cleanly-completed worktrees whose last task shipped no-PR
   and recreate the artifact-loss bug T-270 avoids.
2. **When the predicate holds, reconcile delegates the entire teardown
   to close-wave** via close-wave's "Invocation modes — Reconcile
   delegation" entry point. Close-wave then runs its full archive →
   pr-postprocessor → teardown pipeline for that single worktree.
3. **When the predicate fails**, reconcile falls through to Cases A/B/C
   unchanged. An agent that crashed, wedged, or never wrote
   shutdown-artifacts has nothing to archive; the dirty path
   (cooperative shutdown → `force_unregister` on timeout → direct
   teardown) is the correct response.

See `plugins/cloglog/skills/reconcile/SKILL.md` Step 5.0 for the
predicate check and delegation shape, and
`plugins/cloglog/skills/close-wave/SKILL.md` "Invocation modes" for the
reconcile-driven entry point. The reconcile skill never tears a
predicate-true worktree down directly, and close-wave never runs
without having validated its preconditions (the predicate is that
validation when delegated; user confirmation is that validation when
invoked directly).

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

### Restart-for-new-tools protocol

1. After a merge, the main agent runs `make sync-mcp-dist` (wraps
   `scripts/sync_mcp_dist.py`). The script rebuilds `mcp-server/dist/` via
   `npm run build` and diffs the tool names declared in `dist/server.js`
   before and after. The `close-wave` skill invokes it between
   `git pull origin main` and the main-branch quality gate (step 9.5); it is
   idempotent and a no-op when the tool surface did not change, so it is safe
   to run on every close.
2. If `added`/`removed` is non-empty, the script broadcasts an
   `mcp_tools_updated` event to every online worktree's `.cloglog/inbox`
   plus the main agent inbox:

   ```json
   {"type":"mcp_tools_updated","added":["new_tool_a"],"removed":[],"ts":"..."}
   ```

   Online worktrees are enumerated via
   `GET /api/v1/projects/{project_id}/worktrees` filtered to
   `status='online'`. The gateway's `ApiAccessControlMiddleware` rejects
   unauthenticated access to non-agent routes, so the script sends an
   `X-Dashboard-Key` header sourced from `settings.dashboard_secret`
   (loaded from `.env` the same way the running backend does). The script
   does not shell out to psql and does not require agent credentials.
3. A worktree agent that needs the new tools emits `need_session_restart` to
   the main inbox and pauses (no new MCP calls, no new commits).
4. Main closes the worktree's zellij tab and opens a new one via the launch
   skill; the new Claude session loads the updated MCP tool list at startup.
5. The agent resumes its active task via `register_agent` (the register is
   idempotent; it returns the existing session) and continues.

An agent that receives `mcp_tools_updated` but does NOT need the change keeps
working as normal — no restart, no pause.

#### Why a main-side script, not a git hook or CI job

Three alternatives were considered:

- **Commit `mcp-server/dist/` to git.** Rejected: dist is gitignored at both
  the repo root and `mcp-server/.gitignore`; every future worktree would
  inherit a stale snapshot and regenerate conflicts on every PR.
- **GitHub Action that rebuilds and commits on merge.** Rejected for the
  same reason — plus it introduces a CI-only code path that devs cannot
  reproduce locally.
- **`make promote` step.** Promote rebuilds the prod clone, not the dev
  clone — but the dev clone's `.mcp.json` is what worktrees consume.
  Moving the rebuild to promote would not fix the T-224 → T-225 incident.

A main-side script hooked into `close-wave` is the cheapest correct path:
rebuild runs on the same host that owns the dev `.mcp.json` target, the
broadcast reaches any agents that are still attached, and the whole thing
takes ~1 s.

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
  target. Depends on T-218 and T-221. *Landed; consumer wired through
  `scripts/wait_for_agent_unregistered.py`.*
- **T-221** — Admin `force_unregister`: backend endpoint (project-scoped auth)
  plus MCP tool for tier 2.
- **T-243** — Enforce the `agent_unregistered` inbox event in the agent
  shutdown path and the SessionEnd hook backstop.
- **T-244** — Post-merge mcp-server dist rebuild + `mcp_tools_updated`
  broadcast. Implements Section 6's restart-for-new-tools protocol.
- **T-NEW-a** — Plumb `<project_root>` into worktree-agent environments.
  `plugins/cloglog/skills/launch/SKILL.md`'s `launch.sh` must export a
  variable (proposed name: `CLOGLOG_PROJECT_ROOT`) before `exec claude` so
  worktree agents can locate the supervisor inbox without hardcoding. Also
  update the existing plugin prompts/templates to reference
  `<project_root>/.cloglog/inbox` rather than literal paths.
- **T-NEW-c** — `list_worktrees` MCP tool returning `WorktreeResponse`
  (id, path, status, last_heartbeat, branch_name, current_task_id) for
  the caller's project. *Landed in PR #182 (round 2) alongside T-220;
  consumed by close-wave Step 5a (map git-detected paths → UUIDs,
  survives supervisor restart) and reconcile Cases A/B/C (merged-but-
  registered, wedged, orphaned).*
- **T-NEW-b** — Relax the pipeline guard's predecessor-resolution rule at
  `src/agent/services.py:237` so that a `review`-status spec/plan predecessor
  is "resolved" when `artifact_path` is set, regardless of whether `pr_url`
  is also set (i.e., allow `skip_pr=True` predecessors). Without this, the
  Section 1 Trigger B flow for plan tasks leaves downstream impl tasks
  blocked even after `report_artifact` records the plan file. Backend only;
  no schema change.

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
- `plugins/cloglog/agents/worktree-agent.md:56–59` + `claude-md-fragment.md:32–34`
  — plan tasks framed as "Commit the plan locally — NO PR needed. Proceed
  immediately." The commit and no-PR part is correct; the missing piece is
  that the agent must also call `update_task_status(..., review, skip_pr=True)`
  followed by `report_artifact(...)` before proceeding. Without those two
  calls, the board never records the artifact and the impl predecessor
  check fails. See Section 1 Trigger B and T-NEW-b.
- `plugins/cloglog/agents/worktree-agent.md:133, 139` — legacy `/tmp/...`
  inbox paths are flagged above under T-215/T-216, but note that the
  send-to-another-agent example (line 139) hardcodes a target worktree-id in
  its path. The replacement must use the receiving worktree's
  `worktree_path` (from the worktrees table) plus `/.cloglog/inbox`.
