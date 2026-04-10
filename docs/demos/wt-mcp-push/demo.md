# Demo: F-37 Push-Based Agent Message Delivery — Design Spec

## Task
T-166: Write design spec for F-37 (Push-Based Agent Message Delivery via MCP Notifications)

## Research Summary

### Question: Can MCP `notifications/message` push content to Claude's conversation?

**Answer: No.**

Claude Code receives `notifications/message` from MCP servers but does **not** inject them into the model's conversation context. They are silently consumed by the MCP client layer.

Evidence: [GitHub Issue #3174](https://github.com/anthropics/claude-code/issues/3174)

### All MCP Push Mechanisms Evaluated

| Mechanism | Viable? | Why |
|-----------|---------|-----|
| `notifications/message` (logging) | No | Not surfaced to model |
| `notifications/resources/updated` | No | Triggers re-fetch, doesn't inject content |
| `notifications/tools/list_changed` | No | Just triggers re-list |
| Streamable HTTP + SSE | No | Claude Code uses stdio only |
| `system-reminder` tags | No | Internal mechanism, not MCP |

### MCP SDK API Confirmed

    // McpServer.sendLoggingMessage() available
    server.sendLoggingMessage({
      level: 'info',
      logger: 'cloglog',
      data: 'message text'
    })

    // Requires logging capability in server options
    new McpServer(info, { capabilities: { logging: {} } })

## Design Decision

Since no MCP push path exists, the design uses **fast polling + explicit tool**:

1. **Configurable heartbeat** — reduce from 60s to 10s (env var `CLOGLOG_HEARTBEAT_INTERVAL_MS`)
2. **`check_messages` tool** — lightweight tool agents call to drain pending messages
3. **MCP server instructions** — tell agents to call `check_messages` periodically
4. **Logging notifications** — emit `sendLoggingMessage()` as future-proofing for when Claude Code supports it
5. **Keep `drainMessages()` fallback** — existing piggyback on tool responses stays as guaranteed delivery

## Key Architecture Decisions

- **No database changes** — messages table is already correct
- **No API changes** — heartbeat already returns `pending_messages`
- **Additive only** — backward compatible, existing delivery path preserved
- **Files changed:** `server.ts`, `heartbeat.ts`, `index.ts`, `package.json`

## Spec Location

`docs/specs/F-37-push-message-delivery.md`
