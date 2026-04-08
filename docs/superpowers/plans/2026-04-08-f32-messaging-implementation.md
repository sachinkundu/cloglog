# Implementation Plan: F-32 Cross-Session Agent Messaging

## What Exists (from prototype)

The prototype (PR #68, merged) delivered working code:

| Component | File | Status |
|-----------|------|--------|
| `agent_messages` DB table | `src/agent/models.py` | Done |
| Alembic migration | `src/alembic/versions/e4f5a6b7c8d9_add_agent_messages.py` | Done |
| `queue_message()` repo method | `src/agent/repository.py` | Done |
| `drain_messages()` repo method | `src/agent/repository.py` | Done |
| `send_message()` service method | `src/agent/services.py` | Done |
| Heartbeat returns `pending_messages` | `src/agent/services.py` | Done |
| `POST /agents/{id}/message` endpoint | `src/agent/routes.py` | Done |
| `SendMessageRequest` schema | `src/agent/schemas.py` | Done |
| `HeartbeatResponse.pending_messages` | `src/agent/schemas.py` | Done |
| `send_agent_message` MCP tool | `mcp-server/src/server.ts` | Done |
| `send_agent_message` handler | `mcp-server/src/tools.ts` | Done |
| `drainMessages()` on tool responses | `mcp-server/src/server.ts` | Done |
| `test_notification` prototype tool | `mcp-server/src/server.ts` | **Remove** |

## What's Missing

### 1. Backend Tests

No tests exist for the messaging functionality. Need:

**Repository tests** (in `tests/agent/test_unit.py`, `TestAgentRepository` class):
- `test_queue_message` — insert a message, verify it's in DB with correct fields
- `test_drain_messages_returns_undelivered` — queue 2 messages, drain, verify both returned and marked delivered
- `test_drain_messages_skips_delivered` — queue a message, drain once, drain again → empty
- `test_drain_messages_preserves_order` — queue 3 messages, verify returned in created_at order

**Service tests** (in `tests/agent/test_unit.py`, `TestAgentService` class):
- `test_send_message` — verify message is queued in DB
- `test_send_message_unknown_worktree` — verify ValueError raised
- `test_heartbeat_returns_pending_messages` — queue a message, heartbeat, verify messages in response
- `test_heartbeat_drains_messages` — queue, heartbeat, heartbeat again → empty messages

**Integration tests** (in `tests/agent/test_integration.py`):
- `test_send_message_endpoint` — POST to `/agents/{id}/message`, verify 202 response
- `test_send_message_unknown_agent` — POST to invalid worktree_id, verify 404
- `test_heartbeat_delivers_messages` — POST message, then POST heartbeat, verify `pending_messages` in response
- `test_message_delivery_marks_delivered` — POST message, heartbeat, POST same message again, heartbeat → only new message

### 2. MCP Server Tests

**Tool handler test** (in `mcp-server/src/__tests__/tools.test.ts`):
- `send_agent_message calls POST /agents/{wt}/message` — verify correct API call with message and sender

### 3. Remove Prototype Tool

Delete the `test_notification` tool from `mcp-server/src/server.ts` (lines 379-409). It was only used to prove `sendLoggingMessage` doesn't work. No longer needed.

### 4. Harden Message Endpoint Auth

Currently `POST /agents/{id}/message` has no auth — any request can send a message to any agent. It should require either:
- MCP service credential (`Authorization` + `X-MCP-Request`) — for the main agent sending via MCP
- Dashboard key (`X-Dashboard-Key`) — for the user or webhook sender

The middleware already handles this since the endpoint is under `/api/v1/agents/`, which allows requests with `Authorization` header. But verify this works correctly for the `send_agent_message` MCP tool path.

### 5. Contract Update

If the API contract (`docs/contracts/`) tracks agent endpoints, add the `POST /agents/{id}/message` endpoint and the `pending_messages` field on `HeartbeatResponse`.

## Implementation Order

All items go into a single PR (this is T-135 + cleanup, not multiple features):

1. Remove `test_notification` tool from server.ts
2. Add repository tests (4 tests)
3. Add service tests (4 tests)
4. Add integration tests (4 tests)
5. Add MCP server tool handler test (1 test)
6. Verify auth on message endpoint
7. Update contract if applicable
8. Run `make quality` + `cd mcp-server && make test`

**Total: ~13 new tests across backend + MCP server.**

## Files to Modify

| File | Change |
|------|--------|
| `mcp-server/src/server.ts` | Remove `test_notification` tool (~30 lines) |
| `mcp-server/src/__tests__/tools.test.ts` | Add `send_agent_message` test |
| `tests/agent/test_unit.py` | Add 8 tests (4 repo, 4 service) |
| `tests/agent/test_integration.py` | Add 4 tests |

## What This Does NOT Cover

- T-130 (GitHub webhook integration) — separate feature
- T-127 (assign_task tool) — separate feature
- SSE acceleration layer — future optimization, not needed for v1
- Heartbeat interval tuning — can be done later via config
