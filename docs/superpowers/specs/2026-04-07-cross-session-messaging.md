# Design Spec: F-32 Reliable Cross-Session Agent Messaging

## Problem

The main agent communicates with worktree agents via `zellij action write-chars`, which sends keystrokes to the active pane. This is unaddressed — if tabs switch at the wrong moment, messages go to the wrong agent. We've seen this happen in practice.

We need addressed, reliable messaging from the main agent (or external events like GitHub webhooks) to specific worktree agents.

## Design

### Architecture

```
                                    ┌──────────────┐
GitHub Webhook ──POST──►            │   Backend    │
Main Agent ─────POST──►  /agents/  │              │
                        {id}/message│  EventBus    │──SSE──► Dashboard UI
                                    │   publishes  │
                                    │ AGENT_MESSAGE│──SSE──► Agent MCP Server (wt-ui)
                                    │              │──SSE──► Agent MCP Server (wt-assign)
                                    └──────────────┘
                                                          │
                                                    stdio notification
                                                          │
                                                          ▼
                                                    Claude Agent Session
```

### Components

#### 1. Backend: Message Endpoint + Event

**New endpoint:** `POST /agents/{worktree_id}/message`

```python
class AgentMessageRequest(BaseModel):
    message: str
    sender: str = "system"  # "main-agent", "webhook", "user"
    context: dict[str, str] | None = None  # e.g., {"pr_number": "63", "action": "commented"}

@router.post("/agents/{worktree_id}/message", status_code=202)
async def send_agent_message(
    worktree_id: UUID, body: AgentMessageRequest, service: ServiceDep
) -> dict[str, str]:
    await service.send_message(worktree_id, body.message, body.sender, body.context)
    return {"status": "delivered"}
```

The service publishes an event:

```python
async def send_message(self, worktree_id, message, sender, context):
    worktree = await self._repo.get_worktree(worktree_id)
    if worktree is None:
        raise ValueError(f"Worktree {worktree_id} not found")

    await event_bus.publish(Event(
        type=EventType.AGENT_MESSAGE,
        project_id=worktree.project_id,
        data={
            "worktree_id": str(worktree_id),
            "message": message,
            "sender": sender,
            "context": context or {},
        },
    ))
```

**No message storage.** Messages are fire-and-forget via the event bus. If the agent's MCP server isn't connected to SSE when the message is sent, it's lost. This is acceptable because:
- The MCP server connects to SSE at startup and stays connected
- If the MCP server is down, the agent is down — no one to receive the message
- For durability (future), we can add a message table, but it's not needed for v1

#### 2. Backend: Agent-Facing SSE Stream

**New endpoint:** `GET /agents/{worktree_id}/stream`

Mirrors the existing project SSE stream (`/projects/{id}/stream`) but filtered to events relevant to a specific agent. Requires agent API key auth.

```python
@router.get("/agents/{worktree_id}/stream")
async def agent_event_stream(worktree_id: UUID, service: ServiceDep):
    """SSE stream for agent-specific events."""
    worktree = await service._repo.get_worktree(worktree_id)
    if worktree is None:
        raise HTTPException(status_code=404)

    async def generate():
        queue = event_bus.subscribe(worktree.project_id)
        try:
            while True:
                event = await queue.get()
                # Only forward events relevant to this agent
                if event.type == EventType.AGENT_MESSAGE:
                    if event.data.get("worktree_id") == str(worktree_id):
                        yield f"event: agent_message\ndata: {json.dumps(event.data)}\n\n"
                elif event.type == EventType.TASK_STATUS_CHANGED:
                    if event.data.get("worktree_id") == str(worktree_id):
                        yield f"event: task_changed\ndata: {json.dumps(event.data)}\n\n"
        finally:
            event_bus.unsubscribe(worktree.project_id, queue)

    return StreamingResponse(generate(), media_type="text/event-stream")
```

#### 3. MCP Server: SSE Subscription + Client Notification

The MCP server subscribes to the agent SSE stream at startup (after registration) and pushes notifications to Claude via `server.sendLoggingMessage()`.

```typescript
// In server.ts, after registration succeeds:
function subscribeToAgentEvents(worktreeId: string, apiUrl: string, apiKey: string) {
  const url = `${apiUrl}/agents/${worktreeId}/stream`
  const eventSource = new EventSource(url, {
    headers: { 'Authorization': `Bearer ${apiKey}` }
  })

  eventSource.addEventListener('agent_message', (event) => {
    const data = JSON.parse(event.data)
    // Push to Claude via MCP logging notification
    server.server.sendLoggingMessage({
      level: 'info',
      logger: 'agent-message',
      data: `📨 Message from ${data.sender}: ${data.message}`
    })
  })

  eventSource.addEventListener('task_changed', (event) => {
    const data = JSON.parse(event.data)
    server.server.sendLoggingMessage({
      level: 'info',
      logger: 'task-event',
      data: `📋 Task ${data.task_id} changed to ${data.new_status}`
    })
  })

  eventSource.onerror = () => {
    // Reconnect automatically (EventSource handles this)
  }

  return eventSource
}
```

**Note on `sendLoggingMessage`:** This sends a `notifications/message` to the Claude client. The Claude Code client renders these as system messages in the conversation context. The agent sees them and can act on them.

**EventSource auth:** The native `EventSource` API doesn't support custom headers. Options:
- Use `eventsource` npm package which supports headers
- Pass API key as query parameter (like dashboard SSE does with `dashboard_key`)
- Use `fetch` with `ReadableStream` instead of EventSource

The `eventsource` package is cleanest. Check if already in dependencies, otherwise add it.

#### 4. New Event Type

Add `AGENT_MESSAGE` to `src/shared/events.py`:

```python
class EventType(str, Enum):
    # ... existing types ...
    AGENT_MESSAGE = "agent_message"
```

### Auth

- `POST /agents/{worktree_id}/message` — requires MCP service credential (`X-MCP-Request` + API key) or dashboard key. Agents cannot message each other directly.
- `GET /agents/{worktree_id}/stream` — requires agent API key (`Authorization: Bearer`). The MCP server passes its API key.

### Use Cases

#### PR Comment Notification (with T-130)
```
1. User comments on PR #63
2. GitHub webhook → POST /webhooks/github (future T-130)
3. Backend looks up PR #63 → finds T-32 → finds worktree wt-assign
4. Backend calls send_message(wt-assign, "PR #63 has a new comment. Read and address it.", "webhook", {"pr_number": "63"})
5. EventBus publishes AGENT_MESSAGE
6. wt-assign MCP server receives via SSE → pushes to Claude
7. Agent reads comment and responds
```

#### Task Assignment (with T-127)
```
1. Main agent calls assign_task(task_id, worktree_id) via MCP
2. Backend sets worktree_id on task
3. Backend calls send_message(worktree_id, "New task assigned: T-126 — Fix agent task count", "main-agent")
4. Agent receives notification → calls get_my_tasks → starts the task
```

#### Shutdown Request
```
1. Main agent calls POST /agents/{id}/request-shutdown
2. Backend sets shutdown_requested = true (existing)
3. Backend also calls send_message(id, "Shutdown requested. Finish current work and exit.", "system")
4. Agent receives immediately instead of waiting for next heartbeat
```

### What This Replaces

| Before | After |
|--------|-------|
| `zellij action write-chars` (unaddressed) | `POST /agents/{id}/message` (addressed by ID) |
| `/loop 5m` polling PR state | SSE push on PR event |
| Heartbeat-based shutdown detection (60s delay) | Immediate SSE notification |
| No way to notify agent of new task | Message triggers `get_my_tasks` |

### Migration

1. Implement the backend endpoint + SSE stream + event type
2. Add SSE subscription to MCP server
3. Both old (polling) and new (push) paths work simultaneously
4. Agents still poll as fallback; push is an acceleration
5. Once stable, reduce poll interval or remove `/loop` requirement

### Testing

- Backend: integration test for message endpoint + SSE delivery
- MCP server: test that SSE events trigger `sendLoggingMessage`
- E2E: send message via API, verify agent receives it (requires real MCP server)

### Open Questions

1. **`sendLoggingMessage` vs other notification types** — does Claude Code surface logging notifications in the agent's conversation? Need to verify this works as expected. If not, we may need a different MCP notification mechanism.
2. **EventSource with auth** — the `eventsource` npm package supports headers, but verify it's compatible with our SSE endpoint.
3. **Message ordering** — SSE delivers in order, but if the agent is processing a tool call when a notification arrives, when does it see it? Need to understand Claude Code's notification handling.
