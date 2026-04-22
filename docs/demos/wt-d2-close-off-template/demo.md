# Every new worktree auto-files a paired close-off task on the board — assigned to the main agent, idempotent on re-run, and wired so close-wave PR events route back through the standard Task.pr_url primary lookup.

*2026-04-21T09:11:19Z by Showboat 0.6.1*
<!-- showboat-id: 585e005f-0c56-45ab-a621-3077fa1f1458 -->

The new endpoint lives under /agents/* (same middleware bucket as register_agent and unregister-by-path) so it authenticates with the project API key — exactly what .cloglog/on-worktree-create.sh has available at bootstrap time via ~/.cloglog/credentials. The route is a thin find-or-create wrapper over BoardService.create_close_off_task.

```bash
grep -n "close-off-task\|create_close_off_task" src/agent/routes.py | head -10
```

```output
269:    "/agents/close-off-task",
273:async def create_close_off_task(
282:    ``mcp__cloglog__create_close_off_task`` MCP tool so every new worktree
315:    task, created = await board_service.create_close_off_task(
```

Idempotency is backed by a dedicated column — tasks.close_off_worktree_id — FK to worktrees.id with ON DELETE SET NULL and a UNIQUE constraint. Postgres treats NULLs as distinct for UNIQUE, so at most one live close-off task per worktree exists, and legacy rows whose worktree was deleted keep living on backlog (the spec's 'task lingers as a flag' requirement).

```bash
grep -n "close_off_worktree_id" src/board/models.py
```

```output
132:    close_off_worktree_id: Mapped[_uuid.UUID | None] = mapped_column(
```

```bash
grep -n "close_off_worktree_id\|add_column\|create_foreign_key\|create_index" src/alembic/versions/d2a1b3c4e5f6_add_close_off_worktree_id_to_tasks.py | head -8
```

```output
1:"""add close_off_worktree_id to tasks
3:Introduces a nullable ``close_off_worktree_id`` column on ``tasks`` with a
10:``close_off_worktree_id`` is silently cleared, and it lingers on the
37:    op.add_column(
39:        sa.Column("close_off_worktree_id", sa.Uuid(), nullable=True),
41:    op.create_foreign_key(
42:        "fk_tasks_close_off_worktree_id",
45:        ["close_off_worktree_id"],
```

The close-off checklist is a Python constant (spec's Option A — no DB-backed template registry until there's a second template). Auto-provisioning the 'Operations' epic and 'Worktree Close-off' feature on first call keeps the caller hands-off.

```bash
grep -n "CLOSE_OFF_EPIC_TITLE\|CLOSE_OFF_FEATURE_TITLE\|close_worktree_template\|Close-off for worktree" src/board/templates.py | head -10
```

```output
12:def close_worktree_template(worktree_name: str) -> tuple[str, str]:
22:        f"Close-off for worktree {worktree_name}.\n"
44:CLOSE_OFF_EPIC_TITLE = "Operations"
45:CLOSE_OFF_FEATURE_TITLE = "Worktree Close-off"
```

The service's find-or-create path first queries by close_off_worktree_id; on hit, returns the existing task (created=false). On miss, it auto-provisions Ops/Close-off, creates the task, and stamps both worktree_id (main agent, when settings.main_agent_inbox_path is configured) and close_off_worktree_id.

```bash
grep -n "create_close_off_task\|find_close_off_task\|main_agent_worktree_id\|close_off_worktree_id" src/board/services.py | head -12
```

```output
342:    async def create_close_off_task(
345:        close_off_worktree_id: UUID,
348:        main_agent_worktree_id: UUID | None = None,
352:        Idempotent on ``close_off_worktree_id``. Returns ``(task, created)``
358:        existing = await self._repo.find_close_off_task(close_off_worktree_id)
410:        fields: dict[str, object] = {"close_off_worktree_id": close_off_worktree_id}
411:        if main_agent_worktree_id is not None:
412:            fields["worktree_id"] = main_agent_worktree_id
```

The MCP tool mcp__cloglog__create_close_off_task wraps the endpoint — same body, same auth (the client routes /agents/close-off-task via the project API key branch, not the agent-token branch). Built into mcp-server/dist/ so live Claude sessions see it immediately after the post-merge sync hook runs.

```bash
grep -n "create_close_off_task\|close-off-task\|isCloseOffTaskRoute" mcp-server/src/server.ts mcp-server/src/tools.ts mcp-server/src/client.ts | head -12
```

```output
mcp-server/src/server.ts:259:    'create_close_off_task',
mcp-server/src/server.ts:266:      const result = await handlers.create_close_off_task({ worktree_path, worktree_name })
mcp-server/src/tools.ts:53:  create_close_off_task(args: { worktree_path: string; worktree_name: string }): Promise<unknown>
mcp-server/src/tools.ts:160:    async create_close_off_task({ worktree_path, worktree_name }) {
mcp-server/src/tools.ts:161:      return client.request('POST', '/api/v1/agents/close-off-task', {
mcp-server/src/client.ts:55:    // T-246: create_close_off_task is a launch-skill / worktree-bootstrap
mcp-server/src/client.ts:59:    const isCloseOffTaskRoute = path === '/api/v1/agents/close-off-task'
mcp-server/src/client.ts:75:    if (isRegisterRoute || isUnregisterByPath || isCloseOffTaskRoute) {
```

```bash

if [[ -f mcp-server/dist/tools.js ]] && [[ -f mcp-server/dist/server.js ]]; then
  echo "mcp-server/dist/built:             ok"
else
  echo "mcp-server/dist/built:             MISSING"
fi
echo "dist_tool_registered:             $(grep -c create_close_off_task mcp-server/dist/tools.js)"
echo "dist_server_registered:           $(grep -c create_close_off_task mcp-server/dist/server.js)"

```

```output
mcp-server/dist/built:             ok
dist_tool_registered:             1
dist_server_registered:           2
```

The worktree-bootstrap hook curls the endpoint with the project API key. It is intentionally non-fatal — if the backend is down or the key is missing, the hook logs and continues rather than wedging worktree creation. The main agent can always re-file the task later via the MCP tool.

```bash
grep -n "close-off-task\|T-246\|_resolve_api_key\|_resolve_backend_url" .cloglog/on-worktree-create.sh | head -12
```

```output
53:# T-246: file a close-off task on the board so worktree teardown is visible
64:_resolve_api_key() {
77:_resolve_backend_url() {
93:  _api_key=$(_resolve_api_key)
94:  _backend_url=$(_resolve_backend_url)
96:    echo "[on-worktree-create] skipping close-off-task creation: no CLOGLOG_API_KEY available" >&2
101:      -X POST "${_backend_url}/api/v1/agents/close-off-task" \
```

The endpoint ships with its own contract file at docs/contracts/d2-close-off-template.openapi.yaml and is picked up by make contract-check. The contract pins the body (worktree_path + worktree_name) and the response (task_id, task_number, worktree_id, worktree_name, created) so frontend and MCP clients have a single source of truth.

```bash
grep -nE "close-off-task|CloseOffTaskCreate|CloseOffTaskResponse" docs/contracts/d2-close-off-template.openapi.yaml | head -10
```

```output
3:  title: cloglog — close-off-task template (T-246)
6:  /api/v1/agents/close-off-task:
28:              $ref: '#/components/schemas/CloseOffTaskCreate'
35:                $ref: '#/components/schemas/CloseOffTaskResponse'
53:    CloseOffTaskCreate:
68:    CloseOffTaskResponse:
```

Five integration tests cover the acceptance criteria: one happy-path (task created + assigned to main), one idempotency (same path → created=false, same id), one 404 (unregistered path), one hierarchy (Ops epic + Close-off feature are reused across worktrees), one webhook routing (AgentNotifierConsumer primary path delivers PR_MERGED into the main inbox via Task.pr_url). All run against a real Postgres database provisioned by conftest.py — no mocks.

```bash

grep "^async def test" tests/agent/test_close_off_task.py \
  | sed "s/^async def /  - /; s/(.*$//"

```

```output
  - test_create_close_off_task_files_one_task_assigned_to_main_agent
  - test_create_close_off_task_is_idempotent
  - test_create_close_off_task_returns_404_for_unregistered_worktree
  - test_create_close_off_task_reuses_ops_epic_and_feature
  - test_webhook_routes_pr_events_to_main_via_task_pr_url
```

```bash
uv run pytest tests/agent/test_close_off_task.py -q 2>&1 | grep -oE "[0-9]+ passed"
```

```output
5 passed
```
