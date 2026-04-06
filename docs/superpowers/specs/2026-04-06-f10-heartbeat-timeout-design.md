# Heartbeat Timeout Cleanup

**Date:** 2026-04-06
**Status:** Design proposal
**Feature:** F-10 — Heartbeat Timeout Cleanup

## Problem

When an agent crashes, loses its network connection, or is killed without triggering the SIGTERM hook, the graceful shutdown mechanism (F-19) never fires. The worktree remains in `status=online` with an active session indefinitely, even though the agent is gone. The dashboard shows a ghost agent that will never respond.

This is the fallback for when graceful shutdown doesn't work. The system needs to detect that an agent has stopped sending heartbeats and automatically clean it up.

## Current State

The building blocks already exist:

- **Heartbeat storage:** Agents call `POST /agents/{worktree_id}/heartbeat` periodically; `Session.last_heartbeat` is updated each time.
- **Timeout config:** `settings.heartbeat_timeout_seconds = 180` (3 minutes).
- **Detection query:** `AgentRepository.get_timed_out_sessions(cutoff)` finds active sessions with `last_heartbeat < cutoff`.
- **Cleanup logic:** `AgentService.check_heartbeat_timeouts()` ends timed-out sessions, sets worktrees offline, and publishes `WORKTREE_OFFLINE` events.

**What's missing:** Nothing calls `check_heartbeat_timeouts()`. There is no background scheduler.

## Design

### Background Task in App Lifespan

Add an asyncio background task to the FastAPI lifespan that runs `check_heartbeat_timeouts()` on a fixed interval. This is the simplest approach — no external scheduler, no cron, no new dependencies.

```python
# In src/agent/scheduler.py
async def run_heartbeat_checker(interval_seconds: int = 60) -> None:
    """Periodically check for timed-out agent sessions."""
    while True:
        await asyncio.sleep(interval_seconds)
        async with get_session() as db:
            repo = AgentRepository(db)
            board_repo = BoardRepository(db)
            service = AgentService(repo, board_repo)
            timed_out = await service.check_heartbeat_timeouts()
            if timed_out:
                logger.info("Cleaned up %d timed-out agents: %s", len(timed_out), timed_out)
```

The lifespan in `src/gateway/app.py` creates this task alongside the existing notification listener. The checker runs every 60 seconds — frequent enough to detect timeouts within one check interval after the 3-minute window, but infrequent enough to be negligible load.

**Why not a separate worker/cron?** This is a single-process application. An in-process asyncio task is the simplest, most reliable approach. It shares the same database connection pool, requires no deployment changes, and is easy to test.

### Check Interval vs Timeout

- **Timeout:** 3 minutes (180s) — how long an agent can be silent before being considered dead.
- **Check interval:** 60 seconds — how often we scan for timeouts.
- **Worst-case detection latency:** ~4 minutes (agent dies right after a heartbeat, timeout fires at 180s, next check runs up to 60s later).

This is acceptable. The cleanup is a fallback mechanism, not a real-time health check.

### What Happens When an Agent Times Out

The existing `check_heartbeat_timeouts()` already handles this correctly:

1. **Session marked `timed_out`:** `session.status = "timed_out"`, `session.ended_at = now()`.
2. **Worktree set offline:** `worktree.status = "offline"`.
3. **SSE event published:** `WORKTREE_OFFLINE` with `reason: "heartbeat_timeout"`.

**Tasks are NOT automatically reassigned or moved.** This is intentional:
- The agent may have partially completed work. Moving tasks to backlog could lose context.
- The master agent (or user) should decide what to do with the orphaned tasks — they receive the `WORKTREE_OFFLINE` event and can act accordingly.
- This matches the current unregister behavior, where tasks remain in their current status after the worktree is deleted.

### What Happens If the Agent Comes Back

If an agent that was timed out calls `register` again with the same `worktree_path`:

1. `upsert_worktree()` finds the existing worktree record, sets it back to `online`.
2. The old timed-out session remains (ended). A new active session is created.
3. The agent resumes with its `current_task` intact (the worktree record preserves `current_task_id`).

This works correctly today — no changes needed. The worktree is a persistent identity; sessions come and go.

### Race Conditions

**Race: Agent sends heartbeat right as checker runs.**
Not a real problem. The checker uses a cutoff timestamp calculated before the query. If the heartbeat lands between cutoff calculation and the query execution, the session's `last_heartbeat` will be after the cutoff and won't be selected. If the heartbeat lands after the session is already marked timed_out, the heartbeat call will fail (no active session found) and the agent should re-register.

**Race: Two checker runs overlap.**
Not possible — there's a single asyncio task running sequentially with `await asyncio.sleep()` between iterations.

**Race: Graceful shutdown fires concurrently with timeout.**
Harmless. Both paths end the session and set the worktree offline. `end_session` is idempotent if the session is already ended (it just updates an already-ended record). The second `WORKTREE_OFFLINE` event is redundant but harmless — the frontend already shows the agent as offline.

### Database Changes

**None.** All required columns and queries already exist.

### UI Implications

The dashboard already handles `WORKTREE_OFFLINE` events via SSE. When a timeout fires:

- The agent card transitions from online to offline.
- The `reason: "heartbeat_timeout"` in the event data could be used to show a distinct visual (e.g., "Timed out" vs "Disconnected"), but this is a frontend concern and not required for the initial implementation.

### Logging

The checker logs at INFO level when it cleans up timed-out agents. No logging on clean iterations to avoid noise.

## Files to Create/Modify

| File | Change |
|------|--------|
| `src/agent/scheduler.py` | **New.** Background task function `run_heartbeat_checker()`. |
| `src/gateway/app.py` | Add the heartbeat checker to the lifespan. |
| `tests/agent/test_unit.py` | Test the scheduler function directly. |
| `tests/agent/test_integration.py` | Integration test: register agent, let heartbeat expire, verify cleanup. |

No migrations. No new dependencies. No API changes.

## Interaction with F-19 (Graceful Shutdown)

F-19 and F-10 form a two-tier shutdown system:

1. **Tier 1 — Cooperative (F-19):** Master agent calls `POST /agents/{id}/request-shutdown`. Agent sees `shutdown_requested: true` on next heartbeat, finishes work, generates artifacts, unregisters cleanly.
2. **Tier 2 — Timeout (F-10):** If the agent never responds (crash, lost connection, stuck), the heartbeat timeout fires after 3 minutes. Session is marked `timed_out`, worktree goes offline, event is published.

The timeout is strictly a fallback. If graceful shutdown succeeds, the agent unregisters before the timeout window, and the checker never fires for that session.

## Testing Strategy

1. **Unit test:** Call `check_heartbeat_timeouts()` with sessions that have old `last_heartbeat` values. Verify sessions are ended, worktrees go offline, events are published.
2. **Unit test:** Verify the scheduler loop calls the check method at the expected interval (mock `asyncio.sleep`).
3. **Integration test:** Register an agent, manipulate `last_heartbeat` to be old, run the check, verify the HTTP response from the worktrees endpoint shows the agent as offline.
4. **Edge case test:** Agent re-registers after timeout — verify it gets a new session and resumes.
