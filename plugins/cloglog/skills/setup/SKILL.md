---
name: setup
description: Register main agent with the board and start inbox monitor. Run this at the start of every session. Also handles inbox queries — "which monitor are you watching", "what monitor is running", "what inbox do you have", "what are the current messages in inbox", "show inbox", "read inbox".
user-invocable: true
---

# Main Agent Setup & Inbox Operations

This skill handles two things:
1. **Session setup** — register and start the inbox monitor (run at session start)
2. **Inbox queries** — answer questions about the monitor and inbox contents (run anytime)

## Detecting intent

- If the user is starting a session or explicitly says `/cloglog setup` → run **Setup Steps** below.
- If the user asks about what monitor is running, which inbox you're watching, or monitor status → run **Monitor Status** below.
- If the user asks to see inbox contents, read messages, or show what's in the inbox → run **Read Inbox** below.

---

## Setup Steps

Execute these in order. Do not respond to the user until all steps are complete.

### 1. Register with the board

```
mcp__cloglog__register_agent(worktree_path: "<current working directory>")
```

Save the returned `worktree_id` — you'll need it for agent operations.

### 2. Start inbox monitor (idempotent)

The inbox file is at `<current working directory>/.cloglog/inbox`. **One inbox monitor per agent process, period.** Persistent monitors are session-local but are NOT auto-stopped on `/clear`, so a naive spawn on every `/cloglog setup` accumulates duplicate tails — every inbox event then fires N times.

Before spawning, reconcile against existing monitors:

1. Call `TaskList`.
2. Filter for running Monitor tasks whose `command` ends in `.cloglog/inbox` and resolves to **this** project's inbox file. Match on path suffix (`/.cloglog/inbox`) and verify the resolved absolute path equals `<current working directory>/.cloglog/inbox` — historical monitors started with the relative path `tail -f .cloglog/inbox` (see the github-bot crash-recovery flow) must still be caught here, otherwise the dedupe is bypassed.
3. Branch on the count of matches:
   - **Exactly one** → reuse it. Tell the user: *"Reusing existing inbox monitor (task `<id>`)."* Do NOT spawn a new Monitor.
   - **Zero** → spawn a fresh persistent monitor. **The inbox file may not exist yet** (the backend creates it on first webhook write), and `tail -f` against a missing file exits immediately — leaving the agent monitor-less. Wrap the tail so the file is materialised first:
     ```
     Monitor(
       command: "mkdir -p <current working directory>/.cloglog && touch <current working directory>/.cloglog/inbox && tail -n 0 -F <current working directory>/.cloglog/inbox",
       description: "Main agent inbox — messages from worktree agents",
       persistent: true
     )
     ```
     `-n 0` (start at end-of-file, only deliver events appended from now on) is the correct semantic for this codebase: the inbox is **append-only for the worktree's entire lifetime** (`src/gateway/webhook_consumers.py` always appends; `request_shutdown` is pinned by `tests/agent/test_unit.py` not to truncate). Re-delivering historical events would re-process already-handled `pr_merged`/`review_submitted` lines and crash `start_task` (see `src/agent/services.py:357-370` — only one active task per agent). To reconcile events that landed while the agent was offline, use the *Check PR Status* drill-down in `plugins/cloglog/skills/github-bot/SKILL.md`, not `tail` history. `-F` (capital) is a defence in depth — if the file is rotated or briefly removed, it re-opens by name instead of dying.
   - **Two or more** → keep the oldest matching monitor (lowest creation time / first in `TaskList` ordering), `TaskStop` each of the others, and tell the user: *"Stopped N duplicate monitor(s); reusing task `<id>`."*

### 3. Reconcile control events on crash recovery

The new monitor starts at end-of-file (`-n 0`), which is correct for `/clear` and re-spawn but means a **supervisor crash** would skip any control lines that worktree agents appended while the supervisor was down. The supervisor inbox carries non-PR events with no GitHub-side equivalent — `agent_unregistered` from `plugins/cloglog/hooks/agent-shutdown.sh:120-155` is the most important: `plugins/cloglog/skills/close-wave/SKILL.md` waits on that exact event to know cleanup can proceed, so a missed `agent_unregistered` leaves a completed worktree looking unfinished.

**If this is a normal session start** (no prior crash): skip this step.

**If you just recovered from a crash** (the previous supervisor session ended unexpectedly, you're not sure whether worktree agents finished while you were down, or close-wave is stuck waiting): inspect the inbox tail one-shot — `Read` the last 100 lines of `<current working directory>/.cloglog/inbox` and look for any line where `"type"` is `"agent_unregistered"`, `"agent_started"`, `"mcp_unavailable"`, `"mcp_tool_error"`, or `"pr_merged"`. Treat each one as if it had just arrived. (A proper offset-tracked replay — analogous to `${CLAUDE_PLUGIN_ROOT}/scripts/wait_for_agent_unregistered.py` which already uses byte offsets for exactly this reason — is the durable fix and is filed as follow-up work; it's out of scope for T-294.)

### 4. Confirm

Tell the user:
- Registered as worktree `<worktree_id>`
- Monitoring inbox at `<path>/.cloglog/inbox`
- Ready to supervise worktree agents

---

## Monitor Status

When the user asks "which monitor are you watching", "what monitor is running", "what inbox do you have", or similar:

1. Use `TaskList` to find running Monitor tasks.
2. Report for each monitor:
   - Description
   - Command being run
   - Task ID
   - Whether it's persistent
   - Status (running/stopped)
3. If no monitors are running, say so and offer to start one with the setup steps above.

---

## Read Inbox

When the user asks "what are the current messages in inbox", "show inbox", "read inbox", or similar:

1. Use the `Read` tool to read `<current working directory>/.cloglog/inbox`.
2. If the file is empty or doesn't exist, tell the user the inbox is empty — no messages received.
3. If there are messages, display them formatted clearly with timestamps if present.

---

## Context

You are the supervisor. Worktree agents write to your inbox when they need help (MCP failures, environment issues, questions). When you receive an inbox notification, diagnose the problem and respond by writing to the agent's inbox or sending a message via MCP.

### Handle `agent_unregistered` — relaunch or close-wave

Worktree agents now exit after each PR merge (one task per session). When you receive `agent_unregistered` from a worktree agent, **immediately** decide whether to relaunch or hand off to close-wave:

1. Extract the `worktree_id` and `worktree` (name) fields from the `agent_unregistered` event.
2. Call `mcp__cloglog__get_active_tasks` and filter for tasks where `worktree_id` matches the unregistered agent's UUID AND `status == "backlog"`. **Do NOT use `mcp__cloglog__get_my_tasks`** — that is scoped to the supervisor's own registration and returns the supervisor's tasks, not the worktree that just unregistered.
3. **If backlog tasks remain** → relaunch in the same zellij tab using the continuation prompt:
   ```bash
   WORKTREE_NAME="<wt-name>"
   WORKTREE_PATH="<abs/path/to/worktree>"  # from the board or the event's artifacts paths
   zellij action go-to-tab-by-name "${WORKTREE_NAME}"
   zellij action write-chars "bash '${WORKTREE_PATH}/.cloglog/launch.sh' 'Read ${WORKTREE_PATH}/AGENT_PROMPT.md and all shutdown-artifacts/work-log-T-*.md files in ${WORKTREE_PATH}, then begin the next task.'"
   zellij action write "13"
   ```
   The new session reads the prior work logs (see worktree-agent **Work-Log Bootstrap**), **calls `register_agent` to bind its new MCP session** (the previous session's `unregister_agent` cleared its per-process state), and starts the next backlog task. The agent resolves the next task UUID via `get_my_tasks` rather than trusting the `task.md` left by the prior session — see the Continuation Prompt section of `plugins/cloglog/skills/launch/SKILL.md` for the residual TODO on supervisor-side `task.md` rewrite.
4. **If no backlog tasks remain** → the worktree is done. Invoke `/cloglog close-wave <wt-name>` to run the cooperative shutdown, consolidate artifacts, and tear down the worktree.

**Why supervisor-driven, not agent-driven.** The agent exits after pr_merged — it cannot check for more tasks after unregistering. The supervisor already receives `agent_unregistered`, has MCP access to inspect the board, and owns the decision about whether to relaunch, reprioritize, or skip a task. Encoding "check for more tasks" in the launcher bash script would duplicate MCP logic the supervisor already owns.

### Stop on MCP failure (supervisor side)

Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating.

Two distinct inbox events can land from a worktree agent hitting MCP trouble — react differently to each:

- **`mcp_unavailable`** — the agent could not reach MCP at startup (ToolSearch returned no matches, or the first post-register call failed at the transport layer). The agent has already exited. Diagnose the outage (is the backend up? was the worktree's `.mcp.json` written? did `CLOGLOG_API_KEY` land in `~/.cloglog/credentials`?) and, once repaired, `force_unregister` the dead session and relaunch the agent.
- **`mcp_tool_error`** — the agent reached MCP but a tool call returned a 5xx, 409 state guard, auth rejection, schema error, or (after one backoff retry) a transient network error. The agent is **still running and waiting** on its inbox Monitor. Inspect the `tool` + `error` fields, fix the root cause (advance a stuck pipeline predecessor, correct board state, resolve a conflict), then write a resume instruction to the agent's inbox (`<worktree_path>/.cloglog/inbox`) or force-unregister if the agent is beyond recovery. Do not ignore the event — the agent cannot self-resume.

See `${CLAUDE_PLUGIN_ROOT}/docs/agent-lifecycle.md` §4.1 for the full rule, both event shapes, and the retry policy that agents must follow.
