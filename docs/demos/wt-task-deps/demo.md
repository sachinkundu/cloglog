# Agents are blocked from starting a task whose parent feature has upstream feature-dependencies with incomplete tasks. The 409 response carries a structured task_blocked payload listing every blocker. The same guard fires on update_task_status transitions into in_progress, closing the direct-PATCH bypass.

*2026-04-19T08:03:04Z by Showboat 0.6.1*
<!-- showboat-id: 397c80e1-64b2-4852-80ef-b055b2b6193c -->

The implementation lives on two layers. Board owns the resolution rule via a new BoardBlockerQueryPort in src/board/interfaces.py; Agent owns the pipeline-predecessor rule in src/agent/interfaces.py. AgentService collects both and raises TaskBlockedError, which src/agent/routes.py translates to a 409 with code=task_blocked.

Proof 1: the Board-context port tests cover the feature-blocker resolution matrix (empty deps, upstream in backlog, upstream done, upstream in review with and without pr_url, multi-feature stable ordering by feature.number, partial feature completion listing only open task numbers).

```bash
uv run pytest tests/board/test_blocker_query.py -q 2>&1 | tail -3 | grep -oP '^\d+ passed'
```

```output
7 passed
```

Proof 2: the Agent-context integration tests hit the real /agents/*/start-task and /agents/*/task-status endpoints and assert (a) cross-worktree chains emit the structured task_blocked 409, (b) cross-worktree chains resolve when upstream moves to review with a pr_url, (c) PATCH into in_progress runs the same guard, (d) the pre-existing 'missing PR URL on review' 409 still has a flat string detail, (e) same-worktree chains hit the pre-existing active-task-guard before the new blocker guard (message: 'agent already has active task(s)').

```bash
uv run pytest tests/agent/test_start_task_blockers.py -q 2>&1 | tail -3 | grep -oP '^\d+ passed'
```

```output
7 passed
```

Proof 3: the new hybrid auth dependency CurrentMcpOrDashboard (src/gateway/auth.py) — used by the T-224 task-dep routes — closes the MCP-key-validation gap on the new write surface. It accepts either a validated MCP service key or a valid dashboard key; rejects garbage Bearer + X-MCP-Request (the existing middleware-only gap).

```bash
uv run pytest tests/gateway/test_mcp_or_dashboard_auth.py -q 2>&1 | tail -3 | grep -oP '^\d+ passed'
```

```output
5 passed
```

Proof 4: existing pipeline-predecessor tests, which used to assert on a flat-string 409 detail, now assert on the structured task_blocked payload (kind=pipeline, predecessor_task_type, reason). Re-running the full agent+board test suite confirms the refactor didn't regress any of the 200+ touched tests.

```bash
uv run pytest tests/agent/ tests/board/ -q 2>&1 | tail -3 | grep -oP '^\d+ passed'
```

```output
234 passed
```

Proof 5: the MCP server surfaces structured 409s as readable text. mcp-server/src/errors.ts defines CloglogApiError with status/code/detail fields; client.ts now parses JSON error bodies instead of flattening to a formatted string; server.ts's wrapHandler renders blockers as bullets when code=task_blocked so agents see 'Feature F-N "title" — incomplete tasks: T-X' rather than a JSON blob.

```bash
cd mcp-server && npx vitest run --reporter=verbose 2>&1 | grep -cE '✓|√'
```

```output
52
```
