# F-37: Push-Based Agent Message Delivery via MCP Notifications

## Status: Draft

## Problem

Agent-to-agent messages sent via `send_agent_message` are invisible when the target agent is busy with non-cloglog tools (Read, Edit, Bash, etc.). Messages are picked up by the 60-second heartbeat and stored in a JS `pendingMessages` array, but only drained into the agent's conversation when the agent calls a cloglog MCP tool (via the `drainMessages()` suffix on tool responses).

If an agent is coding for 10 minutes without calling any cloglog tool, all messages sent during that window are silently buffered and effectively lost until the next cloglog tool call.

## Research Findings

### MCP SDK Notification API

The `@modelcontextprotocol/sdk` provides a `notifications/message` mechanism via `server.sendLoggingMessage()`:

```typescript
// McpServer exposes sendLoggingMessage directly
server.sendLoggingMessage({
  level: 'info',        // debug | info | notice | warning | error | critical | alert | emergency
  logger: 'cloglog',    // optional logger name
  data: 'message text'  // any JSON-serializable value
})

// Or via the underlying Server instance
server.server.notification({
  method: 'notifications/message',
  params: { level: 'info', logger: 'cloglog', data: '...' }
})
```

The server must declare the `logging` capability for this to work. Currently, cloglog-mcp does not declare logging capability.

### Claude Code Does NOT Surface MCP Logging Notifications

**This is the critical finding.** Claude Code receives `notifications/message` from MCP servers but does **not** inject them into the model's conversation context. They are consumed silently by the MCP client infrastructure.

Evidence:
- [GitHub Issue #3174](https://github.com/anthropics/claude-code/issues/3174): "MCP notifications/message Support - Claude Code Receives But Doesn't Display Messages"
- The MCP spec says clients *may* display log messages, but Claude Code does not.

This means `sendLoggingMessage()` cannot be used to deliver agent messages to Claude's conversation context. The message would arrive at Claude Code's MCP client layer and be discarded.

### Other MCP Notification Types Evaluated

| Mechanism | What It Does | Viable? |
|-----------|-------------|---------|
| `notifications/message` (logging) | Sends log entry to client | **No** - not surfaced to model |
| `notifications/resources/updated` | Signals resource changed | **No** - triggers re-fetch, doesn't inject content |
| `notifications/tools/list_changed` | Signals tool list changed | **No** - just triggers re-list |
| Streamable HTTP + SSE | Server pushes events via SSE | **No** - Claude Code uses stdio transport only |
| `system-reminder` tags | Injected into model context | **No** - internal Claude Code mechanism, not MCP |

**Conclusion: No MCP mechanism currently exists to push content into the Claude model's conversation context without a tool call.**

## Design

Given the constraint that MCP provides no push path into the model's context, the design focuses on making the existing poll-based delivery faster and more reliable.

### Approach: Fast Heartbeat with Guaranteed Delivery

The current architecture is actually sound: heartbeat polls the server, picks up messages, and `drainMessages()` appends them to the next tool response. The problem is the 60-second heartbeat interval combined with unpredictable gaps between cloglog tool calls.

The design improves both sides of this:

1. **Shorter heartbeat interval** (configurable, default 10s)
2. **Periodic self-invocation** via a new lightweight tool that the agent is instructed to call regularly

### Component 1: Configurable Heartbeat Interval

**Change:** Make the heartbeat interval configurable via environment variable.

```
CLOGLOG_HEARTBEAT_INTERVAL_MS=10000  # default: 10000 (10 seconds)
```

**File:** `mcp-server/src/heartbeat.ts` (no change to class API)
**File:** `mcp-server/src/server.ts` (pass interval from env)

This ensures messages are picked up from the server within 10 seconds of being sent.

### Component 2: `check_messages` Tool

Add a lightweight MCP tool that the agent can call to drain pending messages without side effects:

```typescript
server.tool(
  'check_messages',
  'Check for pending messages from other agents. Call this periodically during long coding sessions.',
  {},
  async () => {
    const wt = requireRegistered()
    if (typeof wt !== 'string') return wt
    
    // Force an immediate heartbeat to pick up fresh messages
    await heartbeatCallback()
    
    const drained = drainMessages()
    if (!drained) {
      return { content: [{ type: 'text', text: 'No pending messages.' }] }
    }
    return { content: [{ type: 'text', text: drained }] }
  }
)
```

**File:** `mcp-server/src/server.ts`

### Component 3: MCP Server Instructions

Add server instructions that Claude Code injects into the agent's context, telling it to call `check_messages` periodically:

```json
{
  "mcpServers": {
    "cloglog": {
      "command": "node",
      "args": ["mcp-server/dist/index.js"],
      "env": { ... }
    }
  }
}
```

The MCP server should include instructions in its capabilities that are surfaced as `system-reminder` content:

**Implementation note:** The MCP protocol's `initialize` response can include `instructions` in the server info. Claude Code surfaces these as system reminders. Add:

```typescript
const server = new McpServer({
  name: 'cloglog-mcp',
  version: '0.3.0',
}, {
  instructions: 'You have pending messages from other agents that arrive via the cloglog MCP server. Call check_messages every 5-10 tool calls during active coding sessions to avoid missing messages.',
})
```

### Component 4: Logging Capability for Future-Proofing

Even though Claude Code doesn't surface logging notifications today, declare the `logging` capability and emit `sendLoggingMessage()` when messages arrive. This future-proofs the server for when Claude Code (or other MCP clients) starts surfacing these.

```typescript
const server = new McpServer({
  name: 'cloglog-mcp',
  version: '0.3.0',
}, {
  capabilities: {
    logging: {},
  },
  instructions: '...',
})
```

When the heartbeat picks up messages:

```typescript
// In heartbeat callback, after picking up messages:
if (messages && messages.length > 0) {
  pendingMessages.push(...messages)
  // Also emit as logging notification (future-proofing)
  for (const msg of messages) {
    server.sendLoggingMessage({
      level: 'info',
      logger: 'agent-messages',
      data: msg,
    })
  }
}
```

### Component 5: Keep `drainMessages()` Fallback

The existing `drainMessages()` piggyback on tool responses is reliable and should be kept. It acts as a guaranteed delivery path — even if the agent never calls `check_messages`, messages will still be delivered on the next cloglog tool call.

The two delivery paths complement each other:
- **`check_messages` tool**: Agent explicitly polls for messages
- **`drainMessages()` suffix**: Messages piggyback on any cloglog tool response

## Data Flow

```
Agent A                    Backend DB              Agent B's MCP Server        Agent B (Claude)
   |                          |                          |                          |
   |-- send_agent_message --> |                          |                          |
   |                          |-- (heartbeat poll) ----> |                          |
   |                          |                          |-- pendingMessages[] ---> |
   |                          |                          |                          |
   |                          |                          | On next tool call:       |
   |                          |                          |   drainMessages() -----> |
   |                          |                          |                          |
   |                          |                          | OR agent calls:          |
   |                          |                          |   check_messages ------> |
```

## Edge Cases

### Message Ordering
Messages are ordered by `created_at` in the database (`drain_messages` query in `repository.py` orders by `AgentMessage.created_at`). The heartbeat picks them up in order, and they're appended to `pendingMessages` in order. Ordering is preserved.

### Mid-Tool-Call Notifications
If a notification arrives while the agent is mid-tool-call, it's fine: messages accumulate in `pendingMessages` and drain on the next tool response. There's no race condition because the heartbeat callback and tool handlers run in the same Node.js event loop (single-threaded).

### Rate Limiting
With a 10-second heartbeat, the backend receives 6 heartbeat requests per minute per agent. For 10 concurrent agents, that's 60 requests/minute — negligible load. No rate limiting needed.

### Duplicate Delivery
Messages are marked `delivered=True` in the database by `drain_messages()`. They won't be returned again. The JS-side `pendingMessages.splice()` clears them after draining. No duplicate risk.

### Agent Not Registered
If `currentWorktreeId` is null, the heartbeat doesn't fire and `check_messages` returns an error. This is correct behavior.

### Message Backlog
If an agent is offline and messages accumulate, they're all delivered on the first heartbeat after registration. The `drain_messages` query has no limit — it returns all undelivered messages. For very large backlogs, this could be a large response, but in practice agents rarely accumulate more than a handful of messages.

## Migration Path

This is a purely additive change:
1. No database schema changes
2. No API contract changes
3. No breaking changes to existing tools
4. The `drainMessages()` fallback ensures backward compatibility

## Files Changed

| File | Change |
|------|--------|
| `mcp-server/src/server.ts` | Add `check_messages` tool, add logging capability, add server instructions, emit logging notifications in heartbeat |
| `mcp-server/src/heartbeat.ts` | Accept configurable interval (already supported via constructor param) |
| `mcp-server/src/index.ts` | Read `CLOGLOG_HEARTBEAT_INTERVAL_MS` from env, pass to server |
| `mcp-server/package.json` | Bump version to 0.3.0 |

## Testing Strategy

1. **Unit test:** `check_messages` returns "No pending messages" when empty
2. **Unit test:** `check_messages` drains messages and returns them formatted
3. **Unit test:** Heartbeat interval is configurable via env var
4. **Integration test:** Send a message via API, trigger heartbeat, verify message appears in `check_messages` response
5. **Integration test:** Verify `drainMessages()` still works on other tool responses (backward compat)

## Open Questions

1. **Should `check_messages` trigger an immediate heartbeat or just drain the buffer?** Triggering a heartbeat ensures the freshest data but adds a network round-trip. Recommendation: trigger the heartbeat — the 10s interval means the buffer could be up to 10s stale.

2. **Should the CLAUDE.md or agent prompts include an explicit instruction to call `check_messages` every N tool calls?** This is fragile since Claude may not reliably count tool calls. The MCP server `instructions` field is a better place for this guidance, since it's always in context.

3. **When Claude Code eventually supports `notifications/message`, should we remove the `check_messages` tool?** No — keep both paths. The tool is explicit and reliable; the notification is opportunistic and passive. Belt and suspenders.
