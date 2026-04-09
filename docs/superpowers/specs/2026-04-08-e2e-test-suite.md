# Design Spec: F-31 Multi-Agent Coordination E2E Test Suite

## Problem

cloglog's core promise is that multiple autonomous agents work on tasks across projects, coordinated through the board, MCP server, and state machine — without stepping on each other or drifting out of sync. We have unit tests per context and a handful of existing E2E tests, but nothing that exercises the full multi-agent coordination system as a coordinated whole.

The existing E2E tests (`tests/e2e/`) cover basic happy paths (single agent lifecycle, project CRUD, auth) but don't test:
- Multi-agent isolation and concurrency
- Task state machine guards under adversarial conditions
- Multi-project credential isolation
- The three-credential access control model comprehensively
- Board consistency under concurrent operations
- Cross-session messaging delivery
- SSE event ordering and project scoping

## Infrastructure Design

### Test Database Isolation

The existing infrastructure (`tests/conftest.py`) is well-designed and reusable:

- **Session-scoped DB**: Each `pytest` session creates a unique `cloglog_test_{uuid}` PostgreSQL database
- **Schema via `Base.metadata.create_all`**: All models registered in `conftest.py`
- **Teardown**: Database dropped after session, with connection termination

**No changes needed** to the DB isolation strategy. Each test function gets its own project(s) with unique API keys, providing logical isolation within the shared DB.

### Application Setup

The existing `client` fixture in `tests/conftest.py` creates the full app via `create_app()` with all routers mounted, connected to the test DB via dependency override. The `tests/e2e/conftest.py` does the same but redundantly mounts the agent router — this is no longer needed since `create_app()` now includes it.

**Recommendation**: Remove the duplicate `client` fixture in `tests/e2e/conftest.py` and rely on the root `tests/conftest.py` fixture. The E2E conftest should only add E2E-specific fixtures (helpers, multi-agent setup).

### Test Client Configuration

The existing client uses `X-Dashboard-Key: cloglog-dashboard-dev` as default header, which gives dashboard access to all routes. For E2E tests exercising the access control model, we need clients with different credential profiles:

```python
@pytest.fixture
async def agent_client(test_db_name: str) -> AsyncGenerator[AsyncClient, None]:
    """Client with NO default credentials — tests must set headers explicitly."""
    # Same app setup as `client`, but no X-Dashboard-Key default header
    ...

@pytest.fixture
async def mcp_client(test_db_name: str, api_key: str) -> AsyncGenerator[AsyncClient, None]:
    """Client simulating MCP server: Authorization + X-MCP-Request headers."""
    ...
```

### SSE Testing

The `EventBus` is in-process (`src/shared/events.py`), using `asyncio.Queue` per subscriber. Tests can subscribe directly:

```python
queue = event_bus.subscribe(project_id)
# ... trigger an action ...
event = await asyncio.wait_for(queue.get(), timeout=2.0)
assert event.type == EventType.TASK_STATUS_CHANGED
event_bus.unsubscribe(project_id, queue)
```

This avoids the complexity of testing SSE over HTTP. The SSE endpoint (`/projects/{project_id}/stream`) is a thin wrapper over the same event bus — testing the bus directly is sufficient for coordination E2E tests. The SSE HTTP endpoint itself is tested separately in scenario 4 (multi-project isolation).

### Helper Utilities

A shared `tests/e2e/helpers.py` module for common operations:

```python
async def create_project_with_tasks(
    client: AsyncClient,
    n_tasks: int = 3,
    task_types: list[str] | None = None,
) -> ProjectFixture:
    """Create a project with epic > feature > N tasks. Returns IDs and API key."""

async def register_agent(
    client: AsyncClient, api_key: str, worktree_path: str
) -> AgentFixture:
    """Register an agent, return worktree_id and session_id."""

async def full_agent_lifecycle(
    client: AsyncClient, api_key: str, worktree_path: str, task_id: str
) -> None:
    """Register → start task → move to review → unregister."""
```

## PR URL Handling: Test-Mode Project Flag

### The Problem

Moving a task to `review` requires a `pr_url` (line 302-306 in `src/agent/services.py`). In production, this ensures agents actually create PRs. In E2E tests, we don't want to create real GitHub PRs.

### Current State: No URL Format Validation

After reading the codebase thoroughly, the `pr_url` guard only checks:
1. **Not null**: `if status == "review" and not pr_url and not task.pr_url` (services.py:303)
2. **Not reused**: Check against other done tasks in the same feature (services.py:310-318)

There is **no URL format validation** — no regex checking for `github.com`, no HTTP HEAD to verify the PR exists. Any non-empty string satisfies the guard.

### Recommendation: No Infrastructure Needed

Since there's no URL format validation, E2E tests can use **synthetic PR URLs** like:

```python
pr_url = f"https://github.com/test/repo/pull/{random_int}"
```

These satisfy both guards (non-null and unique per feature). No test-mode flag, no local git server, no infrastructure changes.

### Security Analysis

The concern was: "could agents exploit a test-mode flag to bypass PR creation?" This concern doesn't apply because:

1. **The guard is behavioral, not technical.** The `pr_url` field is a string — the backend trusts that the caller provides a real URL. The enforcement that agents actually create PRs is in the agent workflow (CLAUDE.md instructions, hooks), not in URL validation.

2. **Adding URL validation is a separate feature.** If we later add `pr_url` format validation (e.g., must match `github.com/sachinkundu/cloglog/pull/\d+`), we would need a bypass for tests. At that point, the **test-mode project flag** approach is correct:
   - `test_mode: bool` column on `Project`, default `False`
   - Set only via direct DB insert (not API-configurable)
   - When `test_mode=True`, skip URL format validation
   - Agents cannot grant themselves test_mode because the API has no endpoint to set it

3. **The local git server (gitea) approach is overkill.** It adds container orchestration complexity to tests without meaningful security benefit — if an agent can call the test gitea server, it can create "real" PRs there just as easily as using a fake URL string.

### If URL Validation Is Added Later

The spec recommends preparing for this by using a consistent synthetic URL pattern in tests:

```python
E2E_PR_URL_PREFIX = "https://github.com/test/e2e-repo/pull/"

def fake_pr_url() -> str:
    return f"{E2E_PR_URL_PREFIX}{uuid.uuid4().hex[:8]}"
```

If/when URL validation is added, a one-line change to the project fixture (setting `test_mode=True`) enables all existing tests without modification.

## Test Scenarios

### Scenario 1: Agent Lifecycle

Tests the complete agent lifecycle from registration through unregistration.

**Existing coverage**: `test_agent_lifecycle.py` covers basic register, heartbeat, start task, list tasks, unregister. But it's incomplete:
- `test_agent_start_and_complete_task` calls `complete_task` which now always raises (agents can't mark done)
- `test_agent_update_task_status` moves to review without `pr_url`, which should fail

**New/updated tests**:

| Test | What it proves |
|------|---------------|
| `test_register_creates_worktree_and_session` | Registration returns worktree_id, session_id, resumed=False |
| `test_register_existing_path_reconnects` | Same worktree_path → resumed=True, new session, old session ended |
| `test_start_task_transitions_to_in_progress` | Task goes backlog → in_progress, worktree's current_task_id set |
| `test_move_to_review_requires_pr_url` | Moving to review without pr_url → 409 |
| `test_move_to_review_with_pr_url_succeeds` | Moving to review with pr_url → 204, task has pr_url |
| `test_agent_cannot_mark_done` | update_task_status(status="done") → 409 with clear error |
| `test_complete_task_blocked` | complete_task endpoint → 409 "Agents cannot mark tasks as done" |
| `test_heartbeat_returns_status_and_timestamp` | Heartbeat returns ok, last_heartbeat, shutdown_requested=False |
| `test_heartbeat_returns_pending_messages` | Send message → heartbeat → pending_messages contains it |
| `test_shutdown_request_via_heartbeat` | request_shutdown → next heartbeat → shutdown_requested=True |
| `test_unregister_deletes_worktree` | After unregister, worktree disappears from list |
| `test_unregister_with_artifacts` | unregister-by-path with artifact paths → WORKTREE_OFFLINE event has artifacts |

### Scenario 2: Multi-Agent Isolation

Tests that agents sharing a project cannot interfere with each other.

| Test | What it proves |
|------|---------------|
| `test_two_agents_register_independently` | Two worktrees registered, both appear in project worktree list |
| `test_agent_sees_only_own_tasks` | Agent A assigned Task 1, Agent B assigned Task 2 → get_my_tasks returns only own |
| `test_agent_cannot_start_others_task` | Agent A tries to start Agent B's task → 409 (task not assigned to this worktree) |
| `test_agent_one_active_task_guard` | Agent starts Task 1, tries to start Task 2 → 409 "already has active task" |
| `test_unregister_one_leaves_other_active` | Agent A unregisters → Agent B's session/heartbeat still works |
| `test_messages_isolated_between_agents` | Message to Agent A's worktree_id → only Agent A sees it on heartbeat |
| `test_concurrent_heartbeats` | Both agents heartbeat simultaneously (asyncio.gather) → both succeed |

### Scenario 3: Task State Machine

Tests all state transitions and guards.

**State transitions (valid)**:
- `backlog → in_progress` (via start_task)
- `in_progress → review` (via update_task_status with pr_url)
- `review → in_progress` (via update_task_status — feedback cycle)
- `review → done` (via dashboard PATCH, not agent)

**Guard tests**:

| Test | What it proves |
|------|---------------|
| `test_valid_transitions_backlog_to_in_progress` | start_task works on backlog task |
| `test_valid_transition_in_progress_to_review` | update_task_status to review with pr_url succeeds |
| `test_valid_transition_review_to_in_progress` | Agent can move review back to in_progress (feedback loop) |
| `test_dashboard_can_move_to_done` | Dashboard PATCH /tasks/{id} with status=done succeeds |
| `test_skip_state_backlog_to_review_blocked` | Agent cannot skip in_progress (no start_task for this case, but update_task_status from backlog → review should fail because task must be in_progress first) |
| `test_agent_cannot_move_to_done` | update_task_status(status="done") → 409 |
| `test_pipeline_ordering_spec_before_plan` | Create spec and plan tasks. Start plan before spec done → 409 |
| `test_pipeline_ordering_plan_before_impl` | Start impl before plan done → 409 |
| `test_pipeline_ordering_standalone_tasks_skip` | task_type="task" ignores pipeline ordering |
| `test_pr_url_required_for_review` | Any task type → review without pr_url → 409 |
| `test_pr_url_reuse_blocked_same_feature` | Task A done with PR-1, Task B in same feature tries PR-1 → 409 |
| `test_pr_url_reuse_blocked_cross_feature` | Task in Feature A done with PR-1, Task in Feature B tries PR-1 → 409. PRs are unique per project, not per feature. (Note: current code only checks within feature — this test documents the desired behavior and will drive a code fix to make the guard project-wide.) |
| `test_one_active_task_guard` | Start task while another is in_progress → 409 |
| `test_one_active_task_review_counts` | Task in review blocks starting another (review is active). **Future direction**: The user is considering relaxing this to allow starting independent tasks (no pipeline dependency) while another is in review. Since task-level dependency tracking (T-36) isn't implemented yet, the current guard blocks all new tasks when one is active. When task dependencies land, this test should be updated to verify: (a) dependent task blocked while predecessor in review, (b) independent task allowed while unrelated task in review. |

### Scenario 4: Multi-Project Isolation

Tests that two projects with separate API keys are completely isolated.

| Test | What it proves |
|------|---------------|
| `test_separate_projects_separate_keys` | Create Project A and B, each has unique API key |
| `test_agent_in_project_a_cannot_access_project_b_board` | Agent registered in A → GET /projects/{B}/board → 404 or forbidden |
| `test_board_state_independent` | Task changes in A don't appear in B's board |
| `test_sse_events_project_scoped` | Subscribe to A's event bus → action in B → no event received |
| `test_agent_register_wrong_project_key` | Agent with B's key → register with A's project → task from A not accessible |
| `test_entity_numbering_project_scoped` | Project A has T-1, T-2. Project B also starts at T-1 |

### Scenario 5: MCP Server as Gateway (Three-Credential Model)

Tests the access control middleware in `src/gateway/app.py`.

| Test | What it proves |
|------|---------------|
| `test_mcp_access_all_routes` | Authorization + X-MCP-Request → board routes succeed |
| `test_agent_key_only_agent_routes` | Authorization only → /agents/* succeeds. **Design question**: Should agent-facing routes require MCP server mediation (X-MCP-Request) even for `/agents/*`? Currently agents can hit their own routes directly with just a Bearer token. If the intent is that all agent operations go through MCP, this test would change to verify that raw agent keys are rejected everywhere and only MCP credentials work. |
| `test_agent_key_blocked_from_board` | Authorization only → /projects/*/board → 403 |
| `test_dashboard_key_non_agent_routes` | X-Dashboard-Key → board routes succeed |
| `test_dashboard_key_agent_routes_allowed` | X-Dashboard-Key → agent routes (middleware currently passes through). **Design question**: Should dashboard keys be blocked from agent routes? The current middleware only restricts agent-only keys from board routes, but doesn't restrict dashboard keys from agent routes. If the intent is that dashboard and agent are separate credential domains, this test should verify 403 instead. The spec documents current behavior — implementation can tighten this if desired. |
| `test_no_credentials_rejected` | No headers → 401 |
| `test_invalid_dashboard_key_rejected` | X-Dashboard-Key: wrong → 403 |
| `test_health_endpoint_no_auth` | GET /health → 200 (not under /api/v1/) |

Note: The middleware doesn't restrict dashboard keys from agent routes — it only restricts agent-only keys from non-agent routes. The tests must reflect the actual implementation, not assumed behavior.

### Scenario 6: Concurrent Operations

Tests that simultaneous operations don't corrupt state.

| Test | What it proves |
|------|---------------|
| `test_concurrent_task_updates_different_tasks` | Two agents update different tasks via asyncio.gather → both succeed |
| `test_concurrent_start_same_task_one_wins` | Two agents start_task on same task simultaneously → one gets 409 |
| `test_concurrent_task_and_board_no_interference` | Agent updates task while dashboard reads board → both succeed, board consistent |
| `test_sse_events_ordered_under_concurrency` | Multiple simultaneous actions → events arrive in causal order |
| `test_concurrent_registrations_different_paths` | Two agents register simultaneously with different paths → both succeed |

Implementation note: Use `asyncio.gather(call_a, call_b)` to simulate concurrency. Since we're using ASGI transport (in-process), this tests the async path through FastAPI's dependency injection and SQLAlchemy session handling.

### Scenario 7: Board Consistency

Tests that board state is always correct after operations.

| Test | What it proves |
|------|---------------|
| `test_epic_feature_task_hierarchy` | Create epic > feature > tasks → board view shows correct hierarchy |
| `test_feature_status_rollup` | All tasks done → feature status rolls up to done |
| `test_epic_status_rollup` | All features done → epic status rolls up to done |
| `test_partial_rollup_in_progress` | One task in_progress → feature in_progress |
| `test_partial_rollup_review` | One task in review → feature status is review |
| `test_delete_task_updates_counts` | Delete a task → board total_tasks decremented |
| `test_entity_numbering_sequential` | Create 5 tasks → numbers are sequential (T-1 through T-5) |
| `test_bulk_import_creates_hierarchy` | `POST /api/v1/projects/{pid}/import` with nested epics/features/tasks → correct counts, board reflects all entities. (This endpoint exists at `src/board/routes.py:666` and is already tested in `test_project_lifecycle.py:test_bulk_import` and `test_full_workflow.py`.) |
| `test_board_exclude_done_filter` | Request board with exclude_done=True → done tasks omitted |
| `test_board_epic_filter` | Request board with epic_id → only that epic's tasks returned |

### Scenario 8: Drift Detection (Heartbeat Timeout)

Tests the background heartbeat timeout checker.

| Test | What it proves |
|------|---------------|
| `test_heartbeat_timeout_detection` | Register agent, don't heartbeat, call check_heartbeat_timeouts → session marked timed_out |
| `test_timeout_emits_offline_event` | Timeout detection → WORKTREE_OFFLINE event with reason=heartbeat_timeout |
| `test_active_session_not_timed_out` | Agent that recently heartbeated → not flagged |
| `test_timeout_cutoff_boundary` | Session exactly at cutoff boundary → correct behavior |

Implementation note: These tests call `AgentService.check_heartbeat_timeouts()` directly rather than waiting for the background scheduler. The scheduler (`src/agent/scheduler.py`) is a thin `asyncio.sleep` loop — testing the service method covers the logic.

For the timeout to fire, tests must manipulate the `last_heartbeat` timestamp directly in the DB (set it to `now() - timeout - 1s`).

### Scenario 9: Access Control Edge Cases

Deeper access control tests beyond scenario 5.

| Test | What it proves |
|------|---------------|
| `test_agent_key_resolves_to_correct_project` | Register with key A → worktree's project_id matches project A |
| `test_expired_or_rotated_key_rejected` | Delete project → old key → 401 |
| `test_x_api_key_header_fallback` | `X-API-Key` header works as alternative to `Authorization: Bearer` |
| `test_dashboard_key_from_query_param` | `?dashboard_key=...` works (SSE/EventSource fallback) |
| `test_cross_project_task_access_blocked` | Agent in project A → operate on task in project B → appropriate error |

## Cross-Session Messaging Tests

These exercise the messaging system (F-32) end-to-end within the coordination tests:

| Test | What it proves |
|------|---------------|
| `test_send_message_queued` | POST /agents/{id}/message → 202, message in DB |
| `test_heartbeat_drains_messages` | Send message → heartbeat → pending_messages contains it, subsequent heartbeat → empty |
| `test_message_delivery_order` | Send 3 messages → heartbeat → all 3 in order |
| `test_message_to_nonexistent_worktree` | Send to invalid UUID → 404 |
| `test_task_assignment_sends_notification` | assign_task → target agent's heartbeat has "New task assigned" message |

## Test Organization

```
tests/e2e/
├── conftest.py              # E2E-specific fixtures (helpers, multi-agent setup)
├── helpers.py               # Shared test utilities
├── test_agent_lifecycle.py  # Scenario 1 (update existing)
├── test_multi_agent.py      # Scenario 2 (new)
├── test_state_machine.py    # Scenario 3 (new)
├── test_project_isolation.py # Scenario 4 (new)
├── test_access_control.py   # Scenarios 5 + 9 (replace existing test_auth.py)
├── test_concurrency.py      # Scenario 6 (new)
├── test_board_consistency.py # Scenario 7 (new)
├── test_heartbeat_timeout.py # Scenario 8 (new)
├── test_messaging.py        # Cross-session messaging (new)
├── test_full_workflow.py    # Existing (update to fix complete_task)
├── test_project_lifecycle.py # Existing (keep)
├── test_document_flow.py    # Existing (keep)
└── test_document_events.py  # Existing (keep)
```

### Fixing Existing Tests

Two existing tests are broken against the current codebase:

1. **`test_agent_start_and_complete_task`** — calls `complete_task`, which now always raises "Agents cannot mark tasks as done." Fix: Replace with move-to-review flow, then dashboard marks done.

2. **`test_agent_update_task_status`** — moves to review without `pr_url`. Fix: Add `pr_url` parameter.

These should be fixed as part of the implementation, not deferred.

## Test Isolation Between Tests

Each test creates its own project with a unique name and API key. This provides:
- **Data isolation**: Each test's entities are in a separate project namespace
- **No shared mutable state**: No test depends on another test's data
- **Parallelizable**: Tests can run concurrently with `pytest-xdist` if needed

The only shared state is the `EventBus` singleton (`event_bus`). Tests that subscribe to SSE events must subscribe before triggering actions and unsubscribe after, to avoid receiving events from other tests. The project_id scoping on `event_bus.subscribe(project_id)` already handles this naturally.

## CI Integration

### GitHub Actions Workflow

The E2E test suite runs as part of the existing CI pipeline (F-29). Key points:

- **Trigger**: On PR events, only when `src/`, `tests/`, `mcp-server/src/`, or migration files change
- **Service container**: PostgreSQL with `cloglog` user and `cloglog_dev` password (matching test config)
- **Command**: `uv run pytest tests/e2e/ -v --tb=short`
- **Parallel-safe**: Tests use per-session unique DB names, so multiple CI runs don't conflict

### Integration with `make quality`

The E2E tests should be part of `make test` (which `make quality` calls). They already live in the `tests/` directory and use the same pytest config.

### Performance Budget

Target: **< 30 seconds** for the full E2E suite. Each test creates a project, a few entities, and runs a few HTTP calls through ASGI transport — no network overhead. The PostgreSQL session-level DB is created once per test session.

If tests grow beyond 30s, consider:
1. Grouping related assertions into fewer test functions (fewer project setups)
2. Using `pytest-xdist` for parallel execution across workers
3. Sharing project fixtures across related test classes (`@pytest.fixture(scope="class")`)

## What This Does NOT Test

| Excluded | Why |
|----------|-----|
| Actual Claude agent sessions | Would require running Claude, which is slow and non-deterministic |
| Frontend UI interactions | Covered by Playwright E2E (F-22) |
| Real GitHub PR creation/merge | Would require GitHub API access; synthetic URLs are sufficient |
| Zellij tab management | Infrastructure concern, not coordination logic |
| MCP server TypeScript code | The MCP server is a thin HTTP client; testing the backend API directly covers the same logic |
| Background scheduler timing | Test the service method directly; the scheduler is trivial |
| WebSocket/SSE HTTP transport | Test the EventBus directly; the SSE endpoint is a thin wrapper |

## Success Criteria

Running this test suite gives confidence that:

1. **N agents across M projects** can register, work, and unregister without cross-talk
2. **Every state machine guard fires** when it should and allows valid transitions
3. **The three-credential model** enforces proper access boundaries
4. **Concurrent operations** don't corrupt board state
5. **Messages are delivered reliably** via the heartbeat piggyback mechanism
6. **Board roll-up is always consistent** with task statuses
7. **Heartbeat timeout detection** correctly identifies stale sessions

The suite should have **~60 test cases** across 10 test files, covering all 9 scenario groups plus messaging. It should be the definitive answer to "does the multi-agent coordination system work?"
