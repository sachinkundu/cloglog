# Implementation Plan: F-31 Multi-Agent Coordination E2E Test Suite

Based on the approved design spec (`docs/superpowers/specs/2026-04-08-e2e-test-suite.md`, PR #78).

## Implementation Phases

The work is split into 5 phases. Each phase builds on the previous one. All phases are implemented in a single worktree (`wt-e2e`) as one PR.

### Phase 1: Infrastructure & Helpers

**Files**: `tests/e2e/conftest.py`, `tests/e2e/helpers.py`

**Work**:

1. **Clean up `tests/e2e/conftest.py`**:
   - Remove the duplicate `client` fixture that redundantly mounts agent routes (the root `tests/conftest.py` already does this via `create_app()`)
   - Add `bare_client` fixture — same app but NO default `X-Dashboard-Key` header. Used by access control tests that need to set credentials explicitly.
   - Add `db_session` fixture override that provides direct SQLAlchemy session access for tests that need to manipulate DB state (e.g., setting `last_heartbeat` timestamps for timeout tests)

2. **Create `tests/e2e/helpers.py`**:
   ```python
   @dataclass
   class ProjectFixture:
       id: str
       api_key: str
       epic_id: str
       feature_id: str
       task_ids: list[str]

   @dataclass
   class AgentFixture:
       worktree_id: str
       session_id: str

   async def create_project_with_tasks(
       client: AsyncClient,
       n_tasks: int = 3,
       task_types: list[str] | None = None,
   ) -> ProjectFixture

   async def register_agent(
       client: AsyncClient,
       api_key: str,
       worktree_path: str | None = None,
   ) -> AgentFixture

   def auth_headers(api_key: str) -> dict[str, str]
   def mcp_headers(api_key: str) -> dict[str, str]
   def dashboard_headers() -> dict[str, str]

   def fake_pr_url() -> str
   ```

3. **Fix existing broken tests**:
   - `test_agent_lifecycle.py:test_agent_start_and_complete_task` — replace `complete_task` with move-to-review flow
   - `test_agent_lifecycle.py:test_agent_update_task_status` — add `pr_url` parameter
   - `test_full_workflow.py:test_full_workflow` — replace `complete_task` call with dashboard PATCH to move to done

**Validation**: `uv run pytest tests/e2e/ -v` — all existing tests pass.

### Phase 2: Core Scenario Tests (Scenarios 1-3)

**Files**: `tests/e2e/test_agent_lifecycle.py`, `tests/e2e/test_multi_agent.py`, `tests/e2e/test_state_machine.py`

**Work**:

1. **Update `test_agent_lifecycle.py`** (Scenario 1 — 12 tests):
   - Keep existing passing tests
   - Add: `test_register_creates_worktree_and_session`, `test_register_existing_path_reconnects`
   - Add: `test_start_task_transitions_to_in_progress`
   - Add: `test_move_to_review_requires_pr_url`, `test_move_to_review_with_pr_url_succeeds`
   - Add: `test_agent_cannot_mark_done`, `test_complete_task_blocked`
   - Add: `test_heartbeat_returns_status_and_timestamp`, `test_heartbeat_returns_pending_messages`
   - Add: `test_shutdown_request_via_heartbeat`
   - Add: `test_unregister_deletes_worktree`, `test_unregister_with_artifacts`

2. **Create `test_multi_agent.py`** (Scenario 2 — 7 tests):
   - Each test creates a project, registers 2 agents with different worktree paths
   - `test_two_agents_register_independently` — both appear in worktree list
   - `test_agent_sees_only_own_tasks` — assign different tasks, verify isolation
   - `test_agent_cannot_start_others_task` — cross-agent start blocked
   - `test_agent_one_active_task_guard` — already has active task
   - `test_unregister_one_leaves_other_active` — unregister A, B still works
   - `test_messages_isolated_between_agents` — message to A, B's heartbeat empty
   - `test_concurrent_heartbeats` — `asyncio.gather` both heartbeats

3. **Create `test_state_machine.py`** (Scenario 3 — 14 tests):
   - Valid transitions: 4 tests (backlog→in_progress, in_progress→review, review→in_progress, dashboard→done)
   - Guard tests: 3 tests (skip state blocked, agent can't move done, pr_url required)
   - Pipeline ordering: 3 tests (spec before plan, plan before impl, standalone skip)
   - PR URL: 2 tests (reuse blocked same feature, reuse blocked cross feature)
   - One active task: 2 tests (in_progress blocks, review blocks)

   For `test_pr_url_reuse_blocked_cross_feature`: this test documents desired behavior. The current code only checks within feature. The test should be marked with a comment noting it will fail until the guard is made project-wide. Use `pytest.xfail(reason="pr_url guard is currently feature-scoped, needs project-wide fix")` so CI doesn't block.

**Validation**: `uv run pytest tests/e2e/test_agent_lifecycle.py tests/e2e/test_multi_agent.py tests/e2e/test_state_machine.py -v`

### Phase 3: Isolation & Access Control (Scenarios 4-5, 9)

**Files**: `tests/e2e/test_project_isolation.py`, `tests/e2e/test_access_control.py`

**Work**:

1. **Create `test_project_isolation.py`** (Scenario 4 — 6 tests):
   - Each test creates 2 projects with separate API keys
   - `test_separate_projects_separate_keys` — verify different keys
   - `test_agent_in_project_a_cannot_access_project_b_board` — cross-project board access
   - `test_board_state_independent` — changes in A don't appear in B
   - `test_sse_events_project_scoped` — subscribe to A's bus, action in B, no event
   - `test_agent_register_wrong_project_key` — key mismatch
   - `test_entity_numbering_project_scoped` — both start at T-1

2. **Create `test_access_control.py`** (Scenarios 5 + 9 — 13 tests):
   - Uses `bare_client` fixture (no default credentials)
   - Three-credential model (8 tests from Scenario 5):
     - MCP access, agent-only routes, agent blocked from board
     - Dashboard routes, dashboard→agent, no creds, invalid key, health
   - Edge cases (5 tests from Scenario 9):
     - Key resolves correct project, deleted project key rejected
     - X-API-Key fallback, dashboard_key query param, cross-project task access
   - Remove old `test_auth.py` (its coverage is subsumed by `test_access_control.py`)

**Validation**: `uv run pytest tests/e2e/test_project_isolation.py tests/e2e/test_access_control.py -v`

### Phase 4: Concurrency, Consistency, Timeout (Scenarios 6-8)

**Files**: `tests/e2e/test_concurrency.py`, `tests/e2e/test_board_consistency.py`, `tests/e2e/test_heartbeat_timeout.py`

**Work**:

1. **Create `test_concurrency.py`** (Scenario 6 — 5 tests):
   - Uses `asyncio.gather` for concurrent operations
   - `test_concurrent_task_updates_different_tasks`
   - `test_concurrent_start_same_task_one_wins`
   - `test_concurrent_task_and_board_no_interference`
   - `test_sse_events_ordered_under_concurrency`
   - `test_concurrent_registrations_different_paths`

2. **Create `test_board_consistency.py`** (Scenario 7 — 10 tests):
   - Hierarchy, rollup (feature and epic), partial rollup (2 variants)
   - Delete task, entity numbering, bulk import
   - Board filters (exclude_done, epic_id)

3. **Create `test_heartbeat_timeout.py`** (Scenario 8 — 4 tests):
   - Requires direct DB access to manipulate `last_heartbeat` timestamp
   - Calls `AgentService.check_heartbeat_timeouts()` directly
   - `test_heartbeat_timeout_detection` — set old timestamp, verify timed_out
   - `test_timeout_emits_offline_event` — subscribe to event bus, verify WORKTREE_OFFLINE
   - `test_active_session_not_timed_out` — recent heartbeat, not flagged
   - `test_timeout_cutoff_boundary` — exactly at cutoff

**Validation**: `uv run pytest tests/e2e/test_concurrency.py tests/e2e/test_board_consistency.py tests/e2e/test_heartbeat_timeout.py -v`

### Phase 5: Messaging Tests

**Files**: `tests/e2e/test_messaging.py`

**Work**:

1. **Create `test_messaging.py`** (5 tests):
   - `test_send_message_queued` — POST /agents/{id}/message → 202
   - `test_heartbeat_drains_messages` — send, heartbeat gets it, second heartbeat empty
   - `test_message_delivery_order` — 3 messages → heartbeat → all 3 in order
   - `test_message_to_nonexistent_worktree` — invalid UUID → 404
   - `test_task_assignment_sends_notification` — assign_task → heartbeat has "New task assigned"

**Validation**: `uv run pytest tests/e2e/test_messaging.py -v`

## Final Validation

After all phases:

```bash
uv run pytest tests/e2e/ -v --tb=short   # All E2E tests pass
make quality                               # Full quality gate passes
```

**Expected test count**: ~62 tests across 10 test files (existing files updated + 8 new files).

## Implementation Notes

### Patterns to Follow

- **Each test creates its own project** with `create_project_with_tasks()` helper — no shared state
- **Use `fake_pr_url()`** for all PR URL values — unique per call via UUID
- **Agent registration** uses unique worktree paths: `/repo/test-{uuid[:8]}`
- **Event bus tests** subscribe before triggering actions, use `asyncio.wait_for` with 2s timeout
- **Concurrency tests** use `asyncio.gather` — ASGI transport handles async properly
- **Heartbeat timeout tests** manipulate DB directly via `db_session` fixture

### Code Changes Required (Not in This PR)

The spec identified one code fix needed:
- **PR URL uniqueness**: Change guard from feature-scoped to project-scoped (`src/agent/services.py:310-318`). The `test_pr_url_reuse_blocked_cross_feature` test is marked `xfail` until this is fixed.

### File Deletion

- `tests/e2e/test_auth.py` — replaced by `test_access_control.py` with broader coverage

### Dependencies

No new Python dependencies needed. All tests use existing `pytest`, `httpx`, `asyncpg`, `sqlalchemy` infrastructure.
