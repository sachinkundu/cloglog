# Demo: T-135 — Tests and Cleanup for F-32 Agent Messaging

## Summary

Added comprehensive tests for agent messaging (F-32) and removed the prototype `test_notification` tool.

## Changes

### 1. Removed `test_notification` prototype tool
- Deleted from `mcp-server/src/server.ts` — it was only used to prove `sendLoggingMessage` doesn't work in Claude Code

### 2. Fixed 3 pre-existing broken tests (Boy Scout Rule)
- `test_complete_task` and `test_complete_task_returns_next` in `tests/agent/test_unit.py` — replaced with `test_complete_task_blocked` that verifies the ValueError is raised
- `test_full_task_lifecycle` in `tests/agent/test_integration.py` — updated to expect 409 from complete-task endpoint

### 3. Added 4 Repository Tests
- `test_queue_message` — insert a message, verify DB fields
- `test_drain_messages_returns_undelivered` — queue 2, drain, verify both returned and marked delivered
- `test_drain_messages_skips_delivered` — drain twice, second returns empty
- `test_drain_messages_preserves_order` — queue 3, verify created_at ordering

### 4. Added 4 Service Tests
- `test_send_message` — verify message queued in DB
- `test_send_message_unknown_worktree` — verify ValueError raised
- `test_heartbeat_returns_pending_messages` — queue message, heartbeat, verify in response
- `test_heartbeat_drains_messages` — queue, heartbeat, heartbeat again, empty

### 5. Added 4 Integration Tests
- `test_send_message_endpoint` — POST /agents/{id}/message → 202
- `test_send_message_unknown_agent` — POST to invalid ID → 404
- `test_heartbeat_delivers_messages` — POST message then heartbeat, verify pending_messages
- `test_message_delivery_marks_delivered` — message, heartbeat, new message, heartbeat → only new

### 6. Added 1 MCP Server Test
- `send_agent_message calls POST /agents/{wt}/message` — verifies correct API call with message and sender

## Test Results

### Backend Agent Tests (52 passed)
```
tests/agent/test_unit.py::TestAgentRepository::test_queue_message PASSED
tests/agent/test_unit.py::TestAgentRepository::test_drain_messages_returns_undelivered PASSED
tests/agent/test_unit.py::TestAgentRepository::test_drain_messages_skips_delivered PASSED
tests/agent/test_unit.py::TestAgentRepository::test_drain_messages_preserves_order PASSED
tests/agent/test_unit.py::TestAgentService::test_send_message PASSED
tests/agent/test_unit.py::TestAgentService::test_send_message_unknown_worktree PASSED
tests/agent/test_unit.py::TestAgentService::test_heartbeat_returns_pending_messages PASSED
tests/agent/test_unit.py::TestAgentService::test_heartbeat_drains_messages PASSED
tests/agent/test_unit.py::TestAgentService::test_complete_task_blocked PASSED
tests/agent/test_integration.py::TestAgentMessagingAPI::test_send_message_endpoint PASSED
tests/agent/test_integration.py::TestAgentMessagingAPI::test_send_message_unknown_agent PASSED
tests/agent/test_integration.py::TestAgentMessagingAPI::test_heartbeat_delivers_messages PASSED
tests/agent/test_integration.py::TestAgentMessagingAPI::test_message_delivery_marks_delivered PASSED
============================== 52 passed in 5.28s ==============================
```

### MCP Server Tests (24 passed)
```
✓ src/__tests__/tools.test.ts > send_agent_message calls POST /agents/{wt}/message
Test Files  4 passed (4)
     Tests  24 passed (24)
```

### Quality Gate
```
Quality gate: PASSED
```

## Test Delta

| Category | Before | After | Delta |
|----------|--------|-------|-------|
| Backend agent tests | 41 (3 failing) | 52 (0 failing) | +11 new, 3 fixed |
| MCP server tests | 23 | 24 | +1 new |
| Total | 64 (3 failing) | 76 (0 failing) | +12 new, 3 fixed |
