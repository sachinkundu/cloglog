# F-38 Validation: Monitor Tool Confirms Real-Time Agent Messaging

**Date:** 2026-04-12
**Feature:** F-38 — Reliable Claude-to-Claude Agent Messaging
**Predecessor:** [F-38 SOTA Research](f38-agent-messaging-sota.md)
**Status:** Mechanism validated, simplification plan ready

---

## Test Results

Following the SOTA research, we ran three progressively realistic tests to validate the Monitor + file append approach.

### Test 1: Self-test (single session)

Confirmed Monitor delivers `tail -f` events in real-time within a single session.

- Created a file, started `Monitor("tail -f /tmp/inbox")`
- Wrote 3 messages from the same session
- All 3 delivered as instant Monitor notifications
- `tail -f` survives multiple appends (unlike named pipes which close after first writer)

### Test 2: Subagent (Agent tool, background)

Spawned a background subagent that monitored its own inbox file and responded to messages.

- Subagent received all messages via Monitor
- Wrote responses to main agent's inbox
- Main agent's Monitor delivered responses instantly
- Full bidirectional round-trip confirmed

### Test 3: Separate interactive Claude process in zellij (production-identical)

Launched a real Claude session in a zellij tab using the exact same mechanism as worktree agents:
```bash
zellij action new-tab --name "remote-agent" --cwd /home/sachin/code/cloglog
zellij action write-chars "claude --dangerously-skip-permissions 'Read /tmp/remote-agent-prompt.md and follow the instructions exactly.'"
zellij action write 13
```

**Full conversation transcript:**
```
12:41:26  [remote] Online and monitoring. Ready at 12:41:26
          [main]   Welcome! What's your PID and how many MCP tools?
12:43:07  [remote] Shell PID: 146571. I have 57 MCP tools across 4 servers.
          [main]   Quick fire: How many lines is the Makefile?
12:43:38  [remote] Makefile is 117 lines. Ready for question 2.
12:44:00  [main]   What's the latest git commit on main?
12:44:15  [remote] 'Merge pull request #108...' Ready for question 3.
          [main]   Now YOU ask ME a question.
12:44:45  [remote] How many bounded contexts and which has most Python files?
          [main]   4 contexts, gateway has the most.
12:45:23  [remote] I double-checked: agent has 8, not gateway. You were close!
          [main]   Write VERIFIED then goodbye.
12:45:41  [remote] VERIFIED
12:45:41  [remote] Goodbye! Shutting down monitor. It was fun.
```

**Key observations:**
- The remote agent had all 57 MCP tools loaded (4 servers) — identical to a real worktree agent
- It performed real work: file reads, grep, git commands
- It initiated conversation (asked a question, fact-checked the answer)
- Message delivery was instant — all latency was LLM thinking time
- The session ran interactively in a zellij tab (visible for observation)

---

## Impact on F-34 (PR Merge Post-Processing)

F-34 requires: worktree agent sends "PR #NN merged" → main agent receives it → main agent reads PR and creates action items.

**This is fully solved by Monitor + file append.** The implementation is:
1. Main agent runs `Monitor("tail -f /tmp/cloglog-inbox-main", persistent: true)` at session start
2. Worktree agent on PR merge: `echo "[wt-foo] PR #108 merged" >> /tmp/cloglog-inbox-main`
3. Main agent's Monitor fires instantly, spawns subagent to process

No custom messaging infrastructure needed. The Monitor tool IS the transport.

---

## Simplification Plan: What to Remove

The current codebase has a complex heartbeat-piggyback mechanism for message delivery that was built before the Monitor tool existed. With Monitor handling real-time delivery, much of this machinery becomes unnecessary.

### Can Remove Entirely

| Component | Location | Why removable |
|-----------|----------|---------------|
| `drainMessages()` function | `mcp-server/src/server.ts:28-32` | Messages arrive via Monitor, not tool response suffix |
| `pendingMessages` array | `mcp-server/src/server.ts:12` | In-memory buffer between heartbeat and tool calls — no longer needed |
| Heartbeat message pickup (lines 20-23) | `mcp-server/src/server.ts:20-23` | The `pending_messages` extraction from heartbeat response |
| `drainMessages()` calls in 5 tools | `mcp-server/src/server.ts:118,132,147,167,185` | Each tool appends `drainMessages()` to response — remove suffix |
| `HeartbeatResponse.pending_messages` field | `src/agent/schemas.py:36` | Remove from schema — heartbeat becomes pure keepalive + shutdown |
| `drain_messages()` repository method | `src/agent/repository.py:197-213` | No longer called from heartbeat path |
| Heartbeat message formatting in service | `src/agent/services.py:90-95` | The `drain_messages` call and `[{sender}] {message}` formatting |

### Must Keep (Different Purpose)

| Component | Location | Why it stays |
|-----------|----------|-------------|
| Heartbeat timer | `mcp-server/src/heartbeat.ts` | Still needed for session keepalive and shutdown detection |
| Heartbeat shutdown detection (lines 16-18) | `mcp-server/src/server.ts:16-18` | `shutdown_requested` flag — no alternative mechanism |
| `POST /agents/{id}/heartbeat` endpoint | `src/agent/routes.py:54-61` | Keepalive + shutdown signaling — just remove message payload |
| `POST /agents/{id}/message` endpoint | `src/agent/routes.py:177-185` | Keep as API boundary — refactor to write to inbox file |
| `send_agent_message` MCP tool | `mcp-server/src/server.ts:469-480` | Keep — calls the backend endpoint which writes to file |
| `send_message()` service | `src/agent/services.py:102-107` | Keep — validates worktree exists, refactor to write file |
| `agent_messages` DB table | `src/agent/models.py:65-81` | Repurpose as audit log — still valuable for debugging |

### Refactor (Change Implementation)

| Component | Current | New |
|-----------|---------|-----|
| `send_message()` service | Writes to DB, waits for heartbeat drain | Writes to DB (audit) AND appends to inbox file |
| `queue_message()` repository | Inserts into `agent_messages` table | Inserts into table AND appends to `/tmp/cloglog-inbox-{worktree_id}` |
| `shutdownRequested` flag display | Appended to `get_my_tasks` and `complete_task` responses | Could also write to inbox file, or keep as-is (infrequent) |
| Agent bootstrap | Registers via MCP, waits for heartbeat messages | Registers via MCP, starts `Monitor("tail -f inbox")` immediately |

### Tests to Update

| Test | Current Behavior | New Behavior |
|------|-----------------|-------------|
| `test_heartbeat_drains_messages` | Verifies heartbeat response has messages | Remove or replace with file delivery test |
| `test_heartbeat_delivers_messages` | Integration test for drain path | Remove |
| `test_drain_messages_returns_undelivered` | Unit test for drain logic | Remove |
| `test_drain_messages_skips_delivered` | Idempotency test | Remove |
| `test_send_message_queued` | Verifies 202 + DB insert | Keep — endpoint stays |
| `test_message_delivery_order` | FIFO via DB ordering | Update — FIFO via file append ordering |
| `test_message_to_nonexistent_worktree` | 404 on invalid target | Keep — validation stays |
| `test_messages_isolated_between_agents` | Messages don't cross agents | Keep — now verified by separate inbox files |
| `test_task_assignment_sends_notification` | Assignment triggers DB message | Update — verify file write |
| `test_bulk_remove_offline_with_*_messages` | Cleanup of DB messages | Update — cleanup of inbox files |

**Net change: ~5 tests removed, ~4 tests updated, ~6 tests unchanged.**

---

## New Components Needed

### 1. Inbox file convention
```
Path: /tmp/cloglog-inbox-{worktree_id}
Format: one message per line, `[{sender}] {message}\n`
Lifecycle: created on agent registration, cleaned up on worktree removal
```

### 2. Backend file writer (in repository or service)
```python
async def write_to_inbox(self, worktree_id: UUID, message: str, sender: str) -> None:
    """Append message to agent's inbox file for Monitor delivery."""
    inbox_path = f"/tmp/cloglog-inbox-{worktree_id}"
    line = f"[{sender}] {message}\n"
    async with aiofiles.open(inbox_path, "a") as f:
        await f.write(line)
```

### 3. Agent bootstrap Monitor setup
Added to agent prompt / CLAUDE.md instructions:
```
On registration, immediately run:
Monitor("tail -f /tmp/cloglog-inbox-{your_worktree_id}", persistent: true, description: "Agent inbox")
```

### 4. Inbox cleanup on worktree removal
Add to `manage-worktrees.sh remove`:
```bash
rm -f "/tmp/cloglog-inbox-${WORKTREE_ID}"
```

---

## Migration Strategy

### Phase 1: Add Monitor delivery (non-breaking)
- Backend `send_message()` writes to inbox file in addition to DB
- Agent prompts updated to start Monitor on boot
- Heartbeat piggyback still works as fallback
- No code removed yet — both paths active

### Phase 2: Remove piggyback machinery
- Remove `drainMessages()`, `pendingMessages`, heartbeat message pickup
- Remove `pending_messages` from HeartbeatResponse
- Simplify heartbeat to keepalive + shutdown only
- Update/remove affected tests

### Phase 3: Agent launch simplification
- Agents launched via `claude` CLI directly (zellij for visibility only)
- Initial instructions delivered via prompt file, not `write-chars`
- Registration + Monitor setup is the first thing the agent does

---

## Summary

The Monitor tool (Claude Code v2.1.98, April 9 2026) eliminates the need for the heartbeat-piggyback message delivery system. The simplification removes ~7 code components, updates ~4 tests, removes ~5 tests, and replaces a complex multi-hop delivery chain with a direct file append + `tail -f` pattern that delivers messages in sub-second time.

The `agent_messages` table, heartbeat timer, and message API endpoint all survive in simplified forms. The net result is less code, faster delivery, and a system that's easier to reason about.
