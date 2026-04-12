# F-38 Research: Reliable Claude-to-Claude Agent Messaging — State of the Art

**Date:** 2026-04-12
**Feature:** F-38 — Reliable Claude-to-Claude Agent Messaging
**Status:** Research complete, ready for prototyping

---

## Current cloglog Implementation

### What Exists

| Component | Status | Location |
|-----------|--------|----------|
| `agent_messages` DB table | Done | `src/agent/models.py:65-81` |
| `POST /agents/{id}/message` endpoint | Done | `src/agent/routes.py:177-185` |
| Heartbeat returns `pending_messages` | Done | `src/agent/services.py:77-98` |
| `send_agent_message` MCP tool | Done | `mcp-server/src/server.ts:469-480` |
| MCP server `drainMessages()` piggyback | Done | `mcp-server/src/server.ts:28-32` |
| 20 passing tests (unit + integration + e2e) | Done | `tests/` |

### The Delivery Chain

```
send_agent_message → DB (agent_messages) → heartbeat poll (60s) → pendingMessages[] → drainMessages() on next cloglog tool call → agent sees it
```

### Known Gaps

1. **60s heartbeat latency** — Messages sit in DB up to 60s before heartbeat picks them up.
2. **Tool-call dependency** — Even after heartbeat picks up message, it only appears when agent calls one of 6 specific cloglog MCP tools (`get_my_tasks`, `start_task`, `assign_task`, `complete_task`, `update_task_status`). If the agent is coding with Read/Edit/Bash, messages are invisible indefinitely.
3. **No MCP push notifications** — `sendLoggingMessage` was tested and confirmed: Claude Code silently ignores server-initiated MCP notifications. Documented in `docs/superpowers/specs/2026-04-07-cross-session-messaging.md`.
4. **Agent launch depends on zellij `write-chars`** — Sends keystrokes to the active pane. Wrong tab/pane = message goes to wrong agent or nowhere. No launch confirmation.

### The Fundamental Constraint

Claude Code sessions are request-response. There is no interrupt mechanism mid-thought. Sessions only "listen" at tool call boundaries. A server cannot push a message to a Claude session — it can only return data when the session asks for it.

---

## SOTA Research (March-April 2026)

### 1. Claude Code Agent Teams (Anthropic, Built-in, Experimental)

Claude Code now has first-party multi-agent coordination.

- **Enable:** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in settings.json or environment
- **Architecture:** One session acts as team lead, spawns teammate sessions. Each teammate is a separate `claude` CLI process with its own context window.
- **Communication primitives:**
  - `SendMessage` — direct peer-to-peer messaging between any teammates. Supports `message`, `broadcast`, `shutdown_request/response`, and `plan_approval_response` types.
  - `TaskCreate/TaskList/TaskUpdate` — shared task list with dependency tracking and file-based locking.
  - `TeamCreate/TeamDelete` — lifecycle management.
- **Internal implementation:** File-based mailbox system. Messages are JSON blobs written to `~/.claude/teams/{team-name}/inboxes/{agent-name}.json`. Recipients pick up messages between turns (polling their inbox file). No background daemon.
- **Display modes:** In-process (one terminal, Shift+Down to cycle) or split panes (tmux/iTerm2).

**Known bugs (as of April 2026):**
- Inbox polling failures on macOS/tmux — messages remain unread indefinitely (issue #23415)
- SendMessage name mismatch silently drops messages (issue #25135)
- Claude sometimes refuses to delegate and does work inline "for efficiency" despite instructions (issue #42856)
- No session resumption — `/resume` and `/rewind` don't restore teammates
- One team per session, no nested teams, lead is fixed
- All teammates inherit lead's model

**Relevant changelog entries:**

| Date | Version | Change |
|------|---------|--------|
| Mar 17 | v2.1.77 | `SendMessage({to: agentId})` to continue spawned agents |
| Mar 25 | v2.1.83 | `TaskCreated` hook event. Fixed subagent worktree leaks. |
| Mar 26 | v2.1.84 | `agent_id`/`agent_type` in hook events. WorktreeCreate type "http". |
| Mar 29 | v2.1.87 | Fixed messages in Cowork Dispatch not getting delivered. |
| Apr 1 | v2.1.89 | Named subagents in `@` mention typeahead. `PermissionDenied` hook. |
| Apr 9 | v2.1.98 | **Monitor tool** for streaming events from background scripts. |

### 2. Monitor Tool (Anthropic, v2.1.98, April 9 2026)

This is the most significant new capability for our use case.

- **What it does:** Runs a background shell command and streams each stdout line as a real-time event/notification into the Claude session.
- **How it differs from `Bash run_in_background`:** run_in_background is one-shot (notifies on completion). Monitor is for continuous streaming — each line of output wakes the session.
- **Use case for us:** An agent can `Monitor` a log file, named pipe, or message queue. When another agent writes to it, the monitoring agent sees the message immediately — no polling needed.
- **This solves Gap #2** (tool-call dependency): the Monitor tool delivers events regardless of what other tools the agent is using.

### 3. MCP Protocol Updates (Nov 2025 Spec — Current)

The November 2025 MCP spec revision introduced features relevant to inter-agent communication:

**Elicitation (`elicitation/create`):**
- Servers can request structured input from the user during tool execution
- Constrained: can only be sent during a client request (e.g., during `tools/call`), not standalone
- Designed for human-in-the-loop, not agent-to-agent
- Claude Code client support: not confirmed

**Async Tasks:**
- Tool calls can return immediately with a durable handle while work continues in background
- Client can poll task status, list in-flight tasks, cancel
- Both sides must advertise support during initialization
- Still client-initiated — no server push

**StreamableHTTP Transport:**
- Single endpoint for all communication (replaces separate HTTP+SSE)
- Bi-directional: servers can send notifications and requests on the same connection
- HTTP+SSE deprecated, sunset June 30, 2026
- Enables remote MCP servers — but Claude Code CLI uses stdio, not HTTP

**Bottom line:** None of these solve the fundamental "server can't push to Claude Code" constraint. They improve the protocol but don't change the stdio transport's request-response nature.

### 4. Third-Party Solutions

**claude-peers-mcp (1.8k stars, github.com/louislva/claude-peers-mcp):**
- Local broker daemon on `localhost:7899` with SQLite
- Each session's MCP server registers with broker, polls every 1 second
- Messages delivered via `claude/channel` protocol
- Tools: `list_peers`, `send_message`, `set_summary`, `check_messages`
- Limitation: requires `claude.ai` web login, localhost only, last updated January 2026

**AgentHQ / claude-channel:**
- Local MCP channel server for direct agent-to-agent communication
- HTTP listener receives messages, pushes via channel notifications
- Built-in guardrails: one message + one response per exchange with configurable cooldown

**oh-my-claudecode (858+ stars, github.com/yeachan-heo/oh-my-claudecode):**
- 32 specialized agents, 40+ skills, automatic parallelization
- Modes: Team Mode (staged pipeline), Ultrawork/Ultrapilot (up to 5 concurrent workers in isolated git worktrees)
- 3-tier model routing: Haiku for simple, Sonnet for medium, Opus for complex

### 5. Anthropic Official Multi-Agent Guidance

Five coordination patterns published:

1. **Generator-Verifier** — one produces, another evaluates
2. **Orchestrator-Subagent** — central coordinator delegates (recommended for most)
3. **Pipeline** — sequential stages, each specialized
4. **Shared State** — no central coordinator, agents read/write a persistent store directly
5. **Debate/Adversarial** — agents challenge each other

cloglog's architecture (agents + shared board DB + MCP tools) maps to **Shared State**.

Blog posts:
- "How we built our multi-agent research system" — anthropic.com/engineering/multi-agent-research-system
- "Building a C compiler with a team of parallel Claudes" — anthropic.com/engineering/building-c-compiler

### 6. Claude Managed Agents (API, Public Beta — April 8 2026)

- Long-running cloud-hosted agents with persistent state and secure sandboxing
- Multi-agent coordination is NOT in public beta — research preview only
- Not directly relevant to Claude Code CLI sessions, but signals Anthropic's direction

---

## Analysis: Viable Approaches for F-38

### Option A: Monitor Tool + Message Files (Recommended)

```
Sender → POST /agents/{id}/message → DB → backend writes to /tmp/cloglog-inbox-{id}
Recipient → Monitor("tail -f /tmp/cloglog-inbox-{id}") → sees message instantly
```

| Aspect | Assessment |
|--------|-----------|
| Latency | Near-instant (Monitor streams each line) |
| Reliability | High (file-based, no daemon, DB as durable store) |
| Effort | Low (backend writes to file after DB insert, agent runs Monitor at startup) |
| Dependencies | None (Monitor is first-party, shipped Apr 9) |
| Launch problem | Solved — launch via `claude` CLI directly, no zellij write-chars needed |

**How it works:**
1. Backend `send_message` endpoint writes to DB (existing) AND appends to an inbox file
2. Each agent runs `Monitor("tail -f /path/to/inbox-{worktree_id}")` at registration
3. Monitor delivers each new line to the agent's session immediately
4. DB remains the durable store; file is the fast delivery channel
5. Heartbeat piggyback remains as fallback for missed messages

**For agent launch:**
- Launch via `claude --dangerously-skip-permissions -p "Read AGENT_PROMPT.md and begin." &`
- No zellij write-chars dependency
- Zellij used only for visibility/crash recovery, not message delivery
- Agent registers via MCP, starts Monitor on its inbox file

### Option B: Claude Code Agent Teams

| Aspect | Assessment |
|--------|-----------|
| Latency | Between-turn (file polling) |
| Reliability | Medium (known bugs with inbox polling, name mismatches) |
| Effort | Medium (requires rearchitecting around team lead/teammate model) |
| Dependencies | Experimental flag, Anthropic's continued support |
| Launch problem | Solved (team lead spawns teammates directly) |

**Concerns:**
- Experimental, with known bugs
- One team per session, no nested teams — doesn't match our multi-worktree model
- Would replace our custom MCP server coordination with Anthropic's file-based mailbox
- Less reliable than our DB-backed approach
- No persistence across restarts

### Option C: claude-peers-mcp Broker

| Aspect | Assessment |
|--------|-----------|
| Latency | ~1s (polling) |
| Reliability | Medium (third-party, last updated Jan 2026) |
| Effort | Medium (install + configure broker daemon) |
| Dependencies | External daemon, requires claude.ai web login |
| Launch problem | Not solved |

**Concerns:**
- Third-party dependency, unclear maintenance
- Requires claude.ai web login (not API key auth)
- localhost only
- Adds another daemon to manage

### Option D: Hybrid — Monitor + Agent Teams

Use Monitor for real-time message delivery AND Agent Teams for the launch mechanism (team lead spawns teammates instead of zellij write-chars). This combines the best of both.

| Aspect | Assessment |
|--------|-----------|
| Latency | Near-instant (Monitor) |
| Reliability | High (our DB + Monitor, Teams only for launch) |
| Effort | Medium |
| Dependencies | Monitor (stable) + Agent Teams (experimental, only for launch) |

---

## Recommendation

**Option A (Monitor + message files)** is the pragmatic choice:

1. It builds on our existing, tested infrastructure (DB, MCP tools, heartbeat)
2. It solves both gaps: real-time delivery (Monitor) and reliable launch (direct CLI)
3. No experimental flags or third-party dependencies
4. The Monitor tool is first-party, shipped April 9, and is designed exactly for this use case
5. Fallback to heartbeat piggyback if Monitor fails — no single point of failure

**Next steps:**
1. Prototype Monitor-based message delivery between two Claude sessions
2. Verify Monitor actually wakes the session and the agent can act on the message
3. If confirmed: add inbox file writing to the backend message endpoint
4. Add `Monitor("tail -f inbox")` to agent bootstrap sequence
5. Test agent launch via direct `claude` CLI invocation (no zellij write-chars)

---

## Sources

- Claude Code Agent Teams docs — code.claude.com/docs/en/agent-teams
- Claude Code Changelog — code.claude.com/docs/en/changelog
- MCP Spec (2025-11-25) — modelcontextprotocol.io/specification/2025-11-25
- MCP Elicitation — modelcontextprotocol.io/specification/draft/client/elicitation
- MCP Async Tasks — workos.com/blog/mcp-async-tasks-ai-agent-workflows
- claude-peers-mcp — github.com/louislva/claude-peers-mcp
- oh-my-claudecode — github.com/yeachan-heo/oh-my-claudecode
- Monitor tool — claudefa.st/blog/guide/mechanics/monitor
- Anthropic multi-agent research system — anthropic.com/engineering/multi-agent-research-system
- Anthropic C compiler with parallel Claudes — anthropic.com/engineering/building-c-compiler
- Claude Managed Agents — platform.claude.com/docs/en/managed-agents/overview
- GitHub issues: #23415, #25135, #42856, #28300, #28048
- F-32 spec (prior art) — docs/superpowers/specs/2026-04-07-cross-session-messaging.md
