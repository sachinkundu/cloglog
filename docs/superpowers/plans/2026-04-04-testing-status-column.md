# Testing Status Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `testing` status between `in_progress` and `review` so agents document test evidence before requesting review.

**Architecture:** Four small edits across backend, frontend, and MCP server. No migration needed — status is `String(20)`. Roll-up logic treats `testing` as equivalent to `in_progress` at the feature/epic level.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript (frontend), Node.js/TypeScript (MCP server)

---

### Task 1: Backend — Add `testing` to board columns and update roll-up logic

**Files:**
- Modify: `src/board/routes.py:37` (BOARD_COLUMNS list)
- Modify: `src/board/services.py:64-101` (recompute_rollup method)
- Test: `tests/board/test_services.py` (add rollup test)
- Test: `tests/board/test_routes.py` (update board test)

- [ ] **Step 1: Write failing test for rollup with `testing` status**

Add to `tests/board/test_services.py` after the existing rollup tests (after line 101):

```python
async def test_rollup_feature_testing_counts_as_in_progress(service: BoardService, db_session: AsyncSession):
    project, _ = await service.create_project("rollup-testing-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="testing", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="done", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    assert feature.status == "in_progress"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sachin/code/cloglog && python -m pytest tests/board/test_services.py::test_rollup_feature_testing_counts_as_in_progress -v`

Expected: FAIL — `testing` is not in the `("in_progress", "assigned")` tuple at line 70 of `services.py`, so the status falls through to `"planned"` instead of `"in_progress"`.

- [ ] **Step 3: Update roll-up logic to handle `testing`**

In `src/board/services.py`, change line 70 from:

```python
        elif any(s in ("in_progress", "assigned") for s in statuses):
```

to:

```python
        elif any(s in ("in_progress", "assigned", "testing") for s in statuses):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/sachin/code/cloglog && python -m pytest tests/board/test_services.py::test_rollup_feature_testing_counts_as_in_progress -v`

Expected: PASS

- [ ] **Step 5: Write failing test for `testing` column in board response**

Add to `tests/board/test_routes.py` after `test_get_board` (after line 174):

```python
async def test_get_board_includes_testing_column(client: AsyncClient):
    project = (await client.post("/api/v1/projects", json={"name": "testing-col-test"})).json()
    resp = await client.get(f"/api/v1/projects/{project['id']}/board")
    assert resp.status_code == 200
    data = resp.json()
    statuses = [c["status"] for c in data["columns"]]
    assert "testing" in statuses
    # Verify ordering: testing comes after in_progress and before review
    assert statuses.index("testing") == statuses.index("in_progress") + 1
    assert statuses.index("testing") == statuses.index("review") - 1
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd /home/sachin/code/cloglog && python -m pytest tests/board/test_routes.py::test_get_board_includes_testing_column -v`

Expected: FAIL — `testing` is not in `BOARD_COLUMNS`.

- [ ] **Step 7: Add `testing` to BOARD_COLUMNS**

In `src/board/routes.py`, change line 37 from:

```python
BOARD_COLUMNS = ["backlog", "assigned", "in_progress", "review", "done", "blocked"]
```

to:

```python
BOARD_COLUMNS = ["backlog", "assigned", "in_progress", "testing", "review", "done", "blocked"]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd /home/sachin/code/cloglog && python -m pytest tests/board/test_routes.py::test_get_board_includes_testing_column -v`

Expected: PASS

- [ ] **Step 9: Run all backend tests**

Run: `cd /home/sachin/code/cloglog && python -m pytest tests/ -v`

Expected: All tests PASS.

- [ ] **Step 10: Commit backend changes**

```bash
git add src/board/routes.py src/board/services.py tests/board/test_services.py tests/board/test_routes.py
git commit -m "feat(board): add testing status to board columns and roll-up logic"
```

---

### Task 2: Frontend — Add `testing` column label and dot color

**Files:**
- Modify: `frontend/src/components/Column.tsx:11-18` (COLUMN_LABELS)
- Modify: `frontend/src/theme/variables.css:36-42` (column color variable)
- Modify: `frontend/src/components/Column.css:23-28` (dot color rule)
- Test: `frontend/src/components/Column.test.tsx` (add label test)

- [ ] **Step 1: Write failing test for `testing` column label**

Add to `frontend/src/components/Column.test.tsx` inside the `describe('Column', ...)` block, after the `'renders column label for known statuses'` test (after line 29):

```typescript
  it('renders Testing label for testing status', () => {
    const column: BoardColumn = { status: 'testing', tasks: [] }
    render(<Column column={column} onTaskClick={vi.fn()} />)
    expect(screen.getByText('Testing')).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/sachin/code/cloglog/frontend && npx vitest run src/components/Column.test.tsx`

Expected: FAIL — `testing` is not in `COLUMN_LABELS`, so it falls back to the raw string `'testing'` (lowercase), not `'Testing'`.

Wait — actually the fallback is `column.status` which is `'testing'`. The test expects `'Testing'` (capitalized). Let me check... the fallback at line 41 is `COLUMN_LABELS[column.status] ?? column.status`. So without the label, it renders `'testing'` (lowercase). The test expects `'Testing'` (capitalized). This will fail as expected.

- [ ] **Step 3: Add `testing` to COLUMN_LABELS**

In `frontend/src/components/Column.tsx`, change lines 11-18 from:

```typescript
const COLUMN_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  assigned: 'Assigned',
  in_progress: 'In Progress',
  review: 'Review',
  done: 'Done',
  blocked: 'Blocked',
}
```

to:

```typescript
const COLUMN_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  assigned: 'Assigned',
  in_progress: 'In Progress',
  testing: 'Testing',
  review: 'Review',
  done: 'Done',
  blocked: 'Blocked',
}
```

- [ ] **Step 4: Add CSS variable for testing column color**

In `frontend/src/theme/variables.css`, change:

```css
  /* Column colors */
  --col-backlog: #64748b;
  --col-assigned: #22d3ee;
  --col-in-progress: #f59e0b;
  --col-review: #a78bfa;
  --col-done: #10b981;
  --col-blocked: #f97316;
```

to:

```css
  /* Column colors */
  --col-backlog: #64748b;
  --col-assigned: #22d3ee;
  --col-in-progress: #f59e0b;
  --col-testing: #06b6d4;
  --col-review: #a78bfa;
  --col-done: #10b981;
  --col-blocked: #f97316;
```

(`#06b6d4` is cyan-500 — distinct from assigned's cyan-400 and in-progress's amber)

- [ ] **Step 5: Add CSS dot color rule**

In `frontend/src/components/Column.css`, change:

```css
.column-dot.col-backlog { background: var(--col-backlog); }
.column-dot.col-assigned { background: var(--col-assigned); }
.column-dot.col-in_progress { background: var(--col-in-progress); }
.column-dot.col-review { background: var(--col-review); }
.column-dot.col-done { background: var(--col-done); }
.column-dot.col-blocked { background: var(--col-blocked); }
```

to:

```css
.column-dot.col-backlog { background: var(--col-backlog); }
.column-dot.col-assigned { background: var(--col-assigned); }
.column-dot.col-in_progress { background: var(--col-in-progress); }
.column-dot.col-testing { background: var(--col-testing); }
.column-dot.col-review { background: var(--col-review); }
.column-dot.col-done { background: var(--col-done); }
.column-dot.col-blocked { background: var(--col-blocked); }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/sachin/code/cloglog/frontend && npx vitest run src/components/Column.test.tsx`

Expected: All tests PASS including the new `'renders Testing label for testing status'` test.

- [ ] **Step 7: Run all frontend tests**

Run: `cd /home/sachin/code/cloglog/frontend && npx vitest run`

Expected: All tests PASS.

- [ ] **Step 8: Commit frontend changes**

```bash
git add frontend/src/components/Column.tsx frontend/src/components/Column.test.tsx frontend/src/theme/variables.css frontend/src/components/Column.css
git commit -m "feat(frontend): add testing column label, dot color, and CSS variable"
```

---

### Task 3: MCP Server — Update `update_task_status` tool description

**Files:**
- Modify: `mcp-server/src/server.ts:112` (status description string)
- Test: `mcp-server/src/__tests__/` (if tests reference valid statuses)

- [ ] **Step 1: Check if MCP tests reference the status list**

Run: `cd /home/sachin/code/cloglog && grep -r "backlog.*assigned.*in_progress" mcp-server/src/ --include="*.ts"`

If tests validate the description string, they'll need updating too.

- [ ] **Step 2: Update the tool description**

In `mcp-server/src/server.ts`, change line 112 from:

```typescript
      status: z.string().describe('Target status: backlog, assigned, in_progress, review, done, blocked'),
```

to:

```typescript
      status: z.string().describe('Target status: backlog, assigned, in_progress, testing, review, done, blocked'),
```

- [ ] **Step 3: Build MCP server to verify no type errors**

Run: `cd /home/sachin/code/cloglog/mcp-server && npm run build`

Expected: Build succeeds with no errors.

- [ ] **Step 4: Run MCP server tests**

Run: `cd /home/sachin/code/cloglog/mcp-server && make test`

Expected: All tests PASS.

- [ ] **Step 5: Commit MCP server change**

```bash
git add mcp-server/src/server.ts
git commit -m "feat(mcp): add testing to update_task_status valid statuses"
```

---

### Task 4: Quality gate and contract check

**Files:** None (verification only)

- [ ] **Step 1: Run full quality gate**

Run: `cd /home/sachin/code/cloglog && make quality`

Expected: All checks pass (lint, typecheck, tests, contract).

- [ ] **Step 2: Regenerate contract if needed**

If `make contract-check` fails because the board response now includes a `testing` column:

Run: `cd /home/sachin/code/cloglog && make contract-gen` (or equivalent command to update `docs/contracts/baseline.openapi.yaml`)

Then regenerate frontend types and re-run quality gate.

- [ ] **Step 3: Final commit if contract was updated**

```bash
git add docs/contracts/ frontend/src/api/generated-types.ts
git commit -m "chore: update API contract for testing status column"
```
