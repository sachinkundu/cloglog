# F-22: Playwright E2E Test Suite — Implementation Plan

**Date:** 2026-04-06
**Spec:** `docs/superpowers/specs/2026-04-06-f22-playwright-e2e-design.md`

## Implementation Steps

### Step 1: Scaffold Playwright project (foundation)

**Files to create:**
- `tests/e2e/playwright/package.json` — Playwright dependency
- `tests/e2e/playwright/tsconfig.json` — TypeScript config
- `tests/e2e/playwright/playwright.config.ts` — Config with webServer, video, trace settings
- `tests/e2e/playwright/.gitignore` — Ignore test-results/, playwright-report/, node_modules/

**Actions:**
1. Create `tests/e2e/playwright/package.json` with `@playwright/test` dependency
2. Create `tsconfig.json` targeting ES2020+
3. Create `playwright.config.ts` per spec (webServer for backend + frontend, chromium only, video retain-on-failure, trace on-first-retry)
4. Run `npm install` and `npx playwright install chromium`
5. Add `.gitignore` for test artifacts

**Verify:** `cd tests/e2e/playwright && npx playwright test --list` runs without errors (0 tests found is OK).

### Step 2: API helpers and test fixtures

**Files to create:**
- `tests/e2e/playwright/fixtures/api-helpers.ts` — ApiHelper class for seeding data
- `tests/e2e/playwright/fixtures/test-fixtures.ts` — Extended Playwright test with `api` and `seededProject` fixtures

**ApiHelper methods:**
- `createProject(name)` → `POST /projects`
- `createEpic(projectId, title, apiKey)` → `POST /projects/{id}/epics`
- `createFeature(projectId, epicId, title, apiKey)` → `POST /projects/{id}/epics/{id}/features`
- `createTask(projectId, featureId, title, apiKey)` → `POST /projects/{id}/features/{id}/tasks`
- `updateTaskStatus(taskId, status, apiKey)` → `PATCH /tasks/{id}`
- `deleteTask(taskId, apiKey)` → `DELETE /tasks/{id}`

**seededProject fixture:** Creates a project with 1 epic, 1 feature, 3 tasks (one in backlog, one in_progress, one done). Uses `apiKey` for auth on agent-facing endpoints.

**Verify:** Write a trivial smoke test that uses the `seededProject` fixture and asserts the project page loads. Run it.

### Step 3: Navigation tests (`navigation.spec.ts`)

**Tests:**
1. `redirects / to /projects` — goto `/`, expect URL to contain `/projects`
2. `project selector shows projects` — seed project, goto `/projects`, see project name
3. `clicking project navigates to board` — click project, URL becomes `/projects/{id}`
4. `direct URL to task opens detail panel` — goto `/projects/{id}/tasks/{taskId}`, detail panel visible
5. `browser back/forward navigation` — navigate project → task → back → verify URL
6. `page refresh preserves state` — navigate to board, reload, board still visible

**Verify:** All 6 tests pass.

### Step 4: Board view tests (`board.spec.ts`)

**Tests:**
1. `renders all board columns` — verify Backlog, In Progress, Review, Done columns exist
2. `tasks appear in correct columns` — seeded tasks in expected columns
3. `task cards show entity number and title` — verify T-N format on cards
4. `task cards show breadcrumb pills` — verify epic/feature pills with color
5. `clicking task card opens detail panel` — click card, detail panel slides in, URL updates
6. `archive toggle in done column` — archive tasks, verify hidden, toggle shows them

**Selectors needed:** Column headers by text, task cards by title text. May need `data-testid` on columns if ambiguous.

**Verify:** All 6 tests pass.

### Step 5: Backlog tree tests (`backlog.spec.ts`)

**Tests:**
1. `renders epic > feature > task hierarchy` — verify epic header, feature under it, task under feature
2. `epics show colored border and progress counts` — check styles and X/Y text
3. `expand/collapse epics` — click collapse, verify children hidden, expand again
4. `expand/collapse features` — same for features
5. `show completed toggle` — seed all-done feature, verify hidden by default, toggle reveals
6. `clicking backlog task opens detail panel` — click task, panel opens

**Verify:** All 6 tests pass.

### Step 6: Detail panel tests (`detail-panel.spec.ts`)

**Tests:**
1. `task detail shows title, status, priority, description` — verify content rendered
2. `task description renders markdown` — seed task with markdown description, verify rendered HTML
3. `task detail shows breadcrumb pills` — verify epic and feature pills
4. `epic detail shows progress bar and feature list` — navigate to epic detail
5. `feature detail shows task list and parent epic pill` — navigate to feature detail
6. `panel closes on overlay click` — click overlay (data-testid="detail-overlay"), panel disappears
7. `panel closes on close button` — click close button
8. `navigation: click epic pill in task → epic detail` — verify panel switches

**Verify:** All 8 tests pass.

### Step 7: SSE live update tests (`sse-updates.spec.ts`)

**Tests:**
1. `SSE connection established on board load` — intercept /stream request
2. `new task appears without refresh` — create task via API, verify DOM updates
3. `task status change moves card` — update status via API, verify card moves columns
4. `task deletion removes card` — delete via API, verify card disappears
5. `new epic appears in backlog` — create epic via API, verify backlog updates

**Strategy:** Use Playwright's `page.waitForRequest` for SSE verification, `expect(locator).toContainText()` with timeouts for DOM assertions.

**Verify:** All 5 tests pass.

### Step 8: Drag-and-drop tests (`drag-drop.spec.ts`)

**Tests:**
1. `reorder epics in backlog` — drag epic A below epic B, verify order changes
2. `reorder features within epic` — drag feature, verify
3. `reorder tasks within feature` — drag task, verify
4. `order persists after refresh` — reorder, reload, verify order maintained

**Helper:** `dragAndDrop(page, source, target)` using `page.mouse` with 10-step movement per spec.

**Mark as `test.slow()`** — drag tests are inherently slower.

**Verify:** All 4 tests pass.

### Step 9: Search tests (`search.spec.ts`)

**Tests:**
1. `search input opens on focus` — click search (data-testid="search-input"), dropdown appears
2. `typing filters results` — type task title, see matching result
3. `clicking result navigates to detail` — click result, detail panel opens
4. `no results indicator` — search for nonexistent text, see empty state

**Verify:** All 4 tests pass.

### Step 10: Makefile integration and cleanup

**Files to modify:**
- `Makefile` — Add `test-e2e-browser`, `test-e2e-browser-ui`, `test-e2e-browser-headed`, `test-e2e-browser-report` targets

**Actions:**
1. Add Makefile targets per spec
2. Add `tests/e2e/playwright/node_modules/` to root `.gitignore`
3. Run full suite: `make test-e2e-browser`
4. Verify all tests pass end-to-end

## Parallelization Strategy

Steps can be parallelized as follows:
- **Sequential (foundation):** Steps 1 → 2 (must be done first)
- **Parallel (test specs):** Steps 3, 4, 5, 6, 7, 8, 9 can be written in parallel after step 2
- **Sequential (finalize):** Step 10 after all tests are written

For subagent execution: one agent does steps 1-2 (scaffold), then up to 4 agents write test specs in parallel (3+4, 5+6, 7+8, 9+10). Given these are all in `tests/e2e/playwright/`, a single agent is more practical to avoid file conflicts. Use internal task tracking for progress.

## Recommended Approach

Single-agent implementation in this order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10. Each step is a commit. The test specs are independent but share fixtures, so sequential writing avoids merge conflicts while allowing fixture refinement as patterns emerge.

## Data-testid Additions Needed

Based on current frontend code, these `data-testid` attributes already exist:
- `search-input`, `search-dropdown`, `search-result`, `search-loading`, `search-hint`
- `detail-overlay`
- `notif-bell`, `notif-badge`, `notif-dropdown`

May need to add during implementation (if semantic selectors prove insufficient):
- Board columns — currently use CSS class `.column`, can select by heading text
- Task cards — select by title text content
- Backlog epic/feature rows — select by title text content
- Collapse/expand toggles — select by role or aria attributes

Prefer text/role selectors first; add `data-testid` only when tests are flaky without them.
