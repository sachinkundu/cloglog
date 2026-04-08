# Design Spec: F-32 Reliable Cross-Session Agent Messaging

## Problem

The main agent communicates with worktree agents via `zellij action write-chars`, which sends keystrokes to the active pane. This is unaddressed — if tabs switch at the wrong moment, messages go to the wrong agent. We've seen this happen in practice.

We need addressed, reliable messaging from the main agent (or external events like GitHub webhooks) to specific worktree agents.

## Prototype Results

We tested two approaches:

1. **`sendLoggingMessage` (MCP SDK push notification) — FAILED.** The MCP protocol's `notifications/message` from server to client does not surface in Claude Code's conversation context. The notification is silently consumed. This rules out any real-time push via the MCP protocol.

2. **Heartbeat piggyback — WORKS.** Messages stored in DB, returned with the heartbeat response, drained into the next MCP tool response the agent calls. The agent sees the message as part of normal tool output. Tested end-to-end: `send_agent_message` → DB → heartbeat → `get_my_tasks` response included the message.

## Design (Proven)

### Architecture

```
Main Agent ──MCP tool──►  Backend DB  ◄──heartbeat poll──  Agent MCP Server
  (send_agent_message)    agent_messages                        │
                          table                            drainMessages()
                               │                                │
GitHub Webhook ──POST──►       │                          MCP tool response
  (future T-130)               │                                │
                               ▼                                ▼
                          pending_messages              Claude Agent Session
                          returned via                  sees message in tool
                          heartbeat response            output
```

**Key principle:** The main agent sends messages via the `send_agent_message` MCP tool, never by calling the API directly. All agent operations go through MCP.

### Components

#### 1. Backend: Message Storage + Endpoint (IMPLEMENTED)

**Table:** `agent_messages`
```sql
CREATE TABLE agent_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worktree_id UUID REFERENCES worktrees(id) NOT NULL,
    message TEXT NOT NULL,
    sender VARCHAR(100) NOT NULL DEFAULT 'system',
    delivered BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);
CREATE INDEX ix_agent_messages_pending ON agent_messages (worktree_id, delivered);
```

**Endpoint:** `POST /agents/{worktree_id}/message`
- Accepts `{message: str, sender: str}`
- Inserts a row into `agent_messages`
- Returns `202 Accepted` with `{status: "queued"}`

**Heartbeat change:** `POST /agents/{worktree_id}/heartbeat` response now includes:
```json
{
  "status": "ok",
  "last_heartbeat": "...",
  "shutdown_requested": false,
  "pending_messages": ["[main-agent] New task assigned: T-126", "[webhook] PR #63 has comments"]
}
```

Messages are marked `delivered=true` and timestamped when drained.

#### 2. MCP Server: Message Delivery (IMPLEMENTED)

**Sending:** `send_agent_message` tool calls `POST /agents/{id}/message`.

**Receiving:** Heartbeat callback stores `pending_messages` in a local array. A `drainMessages()` helper appends them to tool responses and clears the array. Applied to: `get_my_tasks`, `start_task`, `complete_task`, `update_task_status`.

The agent sees messages like:
```
📨 MESSAGES:
- [main-agent] PR #63 has a new comment. Read and address it.
- [system] New task assigned: T-126 — Fix agent task count
```

#### 3. Latency

- **Max latency:** ~60s (heartbeat interval) + time until next tool call
- **Typical latency:** 30-60s for idle agents, near-instant for actively working agents (they call tools frequently)
- **Improvement path:** Reduce heartbeat interval to 30s for registered agents, or implement SSE as an acceleration layer on top (messages still DB-backed as fallback)

### Auth

- `POST /agents/{worktree_id}/message` — requires MCP service credential (`X-MCP-Request` + API key). Agents cannot message each other directly; the MCP server mediates.
- Heartbeat already requires agent registration.

### Use Cases

#### PR Comment Notification (with T-130)
```
1. User comments on PR #63
2. GitHub webhook → POST /webhooks/github (future T-130)
3. Backend looks up PR #63 → finds T-32 → finds worktree wt-assign
4. Backend inserts into agent_messages: "PR #63 has a new comment. Read and address it."
5. Next heartbeat → MCP server picks up message
6. Next tool call → agent sees message → reads comment → responds
```

#### Task Assignment (with T-127)
```
1. Main agent calls send_agent_message(worktree_id, "New task assigned: T-126")
2. Message stored in agent_messages table
3. Next heartbeat → next tool call → agent sees message
4. Agent calls get_my_tasks → sees T-126 → starts it
```

#### Shutdown Request
```
1. Main agent calls POST /agents/{id}/request-shutdown (existing)
2. Also calls send_agent_message(id, "Shutdown requested. Finish current work and exit.")
3. Agent receives both: shutdown_requested flag + message explaining why
```

### What This Replaces

| Before | After |
|--------|-------|
| `zellij action write-chars` (unaddressed, fragile) | `send_agent_message` MCP tool (addressed by worktree ID, DB-backed) |
| Messages lost if tab switches | Messages stored in DB, delivered on next heartbeat |
| No delivery confirmation | `delivered_at` timestamp in DB |
| No way to notify agent of new task | Message triggers agent to check `get_my_tasks` |

### What This Does NOT Replace (Yet)

| Still needed | Why |
|-------------|-----|
| `/loop` for PR merge detection | Webhook integration (T-130) not yet built |
| Heartbeat polling | Heartbeat is the delivery mechanism, not the problem |

### Future: SSE Acceleration Layer

The heartbeat piggyback has ~60s worst-case latency. For time-sensitive notifications (PR comments, urgent task assignments), an SSE acceleration layer could reduce this to near-instant:

1. MCP server subscribes to `GET /agents/{id}/stream` SSE endpoint
2. On receiving an event, stores the message locally (same `pendingMessages` array)
3. Next tool call delivers it immediately — no need to wait for heartbeat

This is additive — the DB + heartbeat path remains as the reliable fallback. SSE just makes it faster when the connection is healthy. Not needed for v1.

### Testing

- **Backend unit tests:** Message endpoint stores in DB, heartbeat drains messages
- **MCP server tests:** Heartbeat picks up messages, drainMessages appends to tool responses
- **Integration test:** Full flow — send message via MCP, wait for heartbeat, verify tool response includes message

### Implementation Status

| Component | Status |
|-----------|--------|
| `agent_messages` DB table + migration | Done |
| `POST /agents/{id}/message` endpoint | Done |
| Heartbeat returns `pending_messages` | Done |
| `send_agent_message` MCP tool | Done |
| MCP server `drainMessages()` on tool responses | Done |
| `test_notification` prototype tool | Done (can remove) |
| Backend tests | TODO |
| MCP server tests | TODO |
| Remove `test_notification` prototype tool | TODO |
