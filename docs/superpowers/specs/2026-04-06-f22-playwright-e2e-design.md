# F-22: Playwright E2E Test Suite

**Date:** 2026-04-06
**Feature:** F-22 Playwright E2E Test Suite (Epic: Quality & Testing)
**Scope:** End-to-end browser tests covering critical user flows

## Problem

cloglog has unit tests (Vitest + Testing Library for frontend, pytest for backend) and API-level integration tests (`tests/e2e/test_full_workflow.py` via httpx), but zero browser-level E2E tests. Critical user flows — navigation, drag-and-drop reordering, SSE live updates, detail panel interactions — are only tested through mocked component tests that can't catch real integration failures between frontend and backend.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Test framework | Playwright | Industry standard, fast, built-in parallelism, cross-browser, excellent DX with codegen and trace viewer. Already the obvious choice for React + Vite apps. |
| Test data strategy | API seeding via Playwright fixtures | Seed data through real API calls in `beforeAll`/fixtures. Tests run against the real backend + DB, not mocks. Catches real integration issues. |
| Dev server orchestration | `webServer` config in playwright.config.ts | Playwright can start backend + frontend automatically before test runs. No manual server management. |
| Database isolation | Unique test project per test file | Each test file creates its own project via API. No cross-test pollution. Cleanup is optional — test DB is ephemeral. |
| Directory structure | `tests/e2e/` (existing, extend it) | Follows the Makefile convention (`make test-e2e` already points here). Playwright tests go in `tests/e2e/playwright/`. |
| CI integration | Separate from `make quality` initially | E2E tests are slow (~30s+). Run via `make test-e2e-browser` separately. Add to CI pipeline but not the fast quality gate. |
| Browser targets | Chromium only (initially) | Fast feedback loop. Add Firefox/WebKit later if needed. |

## Architecture

```
tests/e2e/
├── conftest.py                    # Existing pytest API-level e2e tests
├── test_full_workflow.py          # Existing API-level e2e tests
└── playwright/
    ├── playwright.config.ts       # Playwright configuration
    ├── package.json               # Playwright dependencies
    ├── fixtures/
    │   ├── test-fixtures.ts       # Shared Playwright fixtures (page, seeded data)
    │   └── api-helpers.ts         # API helper for seeding test data
    ├── tests/
    │   ├── navigation.spec.ts     # Route navigation, URL state
    │   ├── board.spec.ts          # Board view, columns, task cards
    │   ├── backlog.spec.ts        # Backlog tree, expand/collapse, filtering
    │   ├── detail-panel.spec.ts   # Detail panel for epics/features/tasks
    │   ├── drag-drop.spec.ts      # Drag-and-drop reordering
    │   ├── sse-updates.spec.ts    # SSE live update verification
    │   └── search.spec.ts         # Search functionality
    └── tsconfig.json              # TypeScript config for Playwright tests
```

## Playwright Configuration

```typescript
// playwright.config.ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  retries: 1,
  workers: 1, // Sequential — tests share a DB-backed backend
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
  webServer: [
    {
      command: 'make run-backend',
      url: 'http://localhost:8000/health',
      cwd: '../../../..', // repo root from tests/e2e/playwright/
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      cwd: '../../../../frontend',
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});
```

Key choices:
- `workers: 1` — tests run sequentially since they share the same backend/DB. Parallel would require per-worker DB isolation (future optimization).
- `reuseExistingServer: true` — if dev servers are already running, use them. Faster local dev.
- `trace: 'on-first-retry'` — capture trace on failures for debugging.

## Test Data Seeding Strategy

Each test file creates its own isolated project with seeded data via the API:

```typescript
// fixtures/api-helpers.ts
const API_BASE = 'http://localhost:8000/api/v1';

export class ApiHelper {
  async createProject(name: string): Promise<{ id: string; api_key: string }> {
    const res = await fetch(`${API_BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    return res.json();
  }

  async createEpic(projectId: string, title: string, apiKey: string) { ... }
  async createFeature(projectId: string, epicId: string, title: string, apiKey: string) { ... }
  async createTask(projectId: string, featureId: string, title: string, apiKey: string) { ... }
  async updateTaskStatus(taskId: string, status: string, apiKey: string) { ... }
}
```

```typescript
// fixtures/test-fixtures.ts
import { test as base } from '@playwright/test';
import { ApiHelper } from './api-helpers';

type TestFixtures = {
  api: ApiHelper;
  seededProject: {
    projectId: string;
    apiKey: string;
    epicId: string;
    featureId: string;
    taskIds: string[];
  };
};

export const test = base.extend<TestFixtures>({
  api: async ({}, use) => {
    await use(new ApiHelper());
  },
  seededProject: async ({ api }, use) => {
    const project = await api.createProject(`E2E Test ${Date.now()}`);
    const epic = await api.createEpic(project.id, 'Test Epic', project.api_key);
    const feature = await api.createFeature(project.id, epic.id, 'Test Feature', project.api_key);
    const tasks = await Promise.all([
      api.createTask(project.id, feature.id, 'Backlog Task', project.api_key),
      api.createTask(project.id, feature.id, 'In Progress Task', project.api_key),
      api.createTask(project.id, feature.id, 'Done Task', project.api_key),
    ]);
    // Move tasks to different statuses
    await api.updateTaskStatus(tasks[1].id, 'in_progress', project.api_key);
    await api.updateTaskStatus(tasks[2].id, 'review', project.api_key);
    await api.updateTaskStatus(tasks[2].id, 'done', project.api_key);

    await use({
      projectId: project.id,
      apiKey: project.api_key,
      epicId: epic.id,
      featureId: feature.id,
      taskIds: tasks.map(t => t.id),
    });
  },
});
```

## Critical User Flows to Test

### 1. Navigation (`navigation.spec.ts`)
- Landing page redirects `/` to `/projects`
- Project selector lists projects, clicking navigates to `/projects/:id`
- URL reflects current view — refresh preserves state
- Browser back/forward works between board, detail panel, dependency graph
- Direct URL access to `/projects/:id/tasks/:taskId` opens correct detail panel

### 2. Board View (`board.spec.ts`)
- Board renders columns: Backlog, In Progress, Review, Done
- Task cards appear in correct columns based on status
- Task cards show entity number (T-N), title, breadcrumb pills with epic color
- Clicking a task card opens detail panel and updates URL
- Done column has archive toggle; archiving hides tasks, un-archiving restores them
- Board updates reflect correct task counts per column

### 3. Backlog Tree (`backlog.spec.ts`)
- Backlog tree renders epic > feature > task hierarchy
- Epics show colored left border and progress counts (X/Y)
- Expand/collapse works for epics and features
- "Show completed" toggle hides/shows 100%-done items
- Clicking a task in backlog opens detail panel
- Clicking an epic name opens epic detail

### 4. Detail Panel (`detail-panel.spec.ts`)
- Task detail shows: title, description (rendered markdown), status, priority, breadcrumb pills
- Epic detail shows: title, description, progress bar, feature list, documents
- Feature detail shows: title, description, progress bar, task list, parent epic pill, documents
- Document chips are clickable and render markdown content
- Panel closes on close button click and click-outside
- Navigation between detail views (click epic pill in task → opens epic detail)

### 5. Drag and Drop (`drag-drop.spec.ts`)
- Reorder epics in backlog via drag
- Reorder features within an epic via drag
- Reorder tasks within a feature via drag
- Order persists after page refresh (verify via API or re-render)
- Note: dnd-kit drag simulation requires Playwright's `page.mouse` API with precise coordinates

### 6. SSE Live Updates (`sse-updates.spec.ts`)
- Create a task via API while board is open → task appears without refresh
- Change task status via API → card moves to new column without refresh
- Delete a task via API → card disappears without refresh
- Create an epic via API → backlog tree updates without refresh
- Verify EventSource connection is established (check network or DOM updates)

### 7. Search (`search.spec.ts`)
- Search input filters results as user types
- Results show matching epics, features, tasks
- Clicking a search result navigates to the correct detail view
- Empty search shows no results indicator

## Dev Server Orchestration

Playwright's `webServer` config handles starting/stopping servers:

1. **Backend**: `make run-backend` (uvicorn on port 8000, auto-reload)
2. **Frontend**: `cd frontend && npm run dev` (Vite on port 5173, proxies `/api` to backend)
3. **Database**: Must be running (`make db-up`). Playwright config won't start it — document as a prerequisite.

For CI, the sequence is: `make db-up && make db-migrate && npx playwright test`.

## Makefile Integration

```makefile
# New targets
test-e2e-browser:  ## Run Playwright E2E tests
	cd tests/e2e/playwright && npx playwright test

test-e2e-browser-ui:  ## Run Playwright with UI mode (interactive)
	cd tests/e2e/playwright && npx playwright test --ui

test-e2e-browser-headed:  ## Run Playwright in headed mode (visible browser)
	cd tests/e2e/playwright && npx playwright test --headed
```

The existing `make test-e2e` (pytest API-level) stays unchanged. `make test-e2e-browser` is the new Playwright target.

`make quality` does NOT include `test-e2e-browser` — E2E tests are too slow for the fast feedback loop. They run in CI as a separate step.

## Drag-and-Drop Testing Strategy

dnd-kit uses pointer events, not native HTML5 drag. Playwright's approach:

```typescript
async function dragAndDrop(page: Page, source: Locator, target: Locator) {
  const sourceBox = await source.boundingBox();
  const targetBox = await target.boundingBox();

  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
  await page.mouse.down();
  // Move in steps to trigger dnd-kit's activation distance
  await page.mouse.move(
    targetBox.x + targetBox.width / 2,
    targetBox.y + targetBox.height / 2,
    { steps: 10 }
  );
  await page.mouse.up();
}
```

This simulates real mouse interactions, which is exactly what dnd-kit expects.

## SSE Testing Strategy

Two approaches, use both:

1. **Passive observation**: Open board, make API changes, assert DOM updates appear within a timeout:
   ```typescript
   await api.updateTaskStatus(taskId, 'review', apiKey);
   await expect(page.locator('[data-column="review"]')).toContainText('Task Title', { timeout: 5000 });
   ```

2. **EventSource verification**: Check that the SSE connection is established:
   ```typescript
   // Intercept the SSE request
   const ssePromise = page.waitForRequest(req =>
     req.url().includes('/stream') && req.method() === 'GET'
   );
   await page.goto(`/projects/${projectId}`);
   await ssePromise; // SSE connection established
   ```

## Test Data Attributes

Some components may need `data-testid` attributes for reliable selection. Recommended additions:

- `data-testid="column-{status}"` on board columns
- `data-testid="task-card-{taskId}"` on task cards
- `data-testid="backlog-epic-{epicId}"` on backlog epic rows
- `data-testid="backlog-feature-{featureId}"` on backlog feature rows
- `data-testid="detail-panel"` on the detail panel container
- `data-testid="search-input"` on the search box

Where possible, prefer semantic selectors (roles, labels, text) over test IDs. Add test IDs only when semantic selection is ambiguous.

## Dependencies

```json
// tests/e2e/playwright/package.json
{
  "devDependencies": {
    "@playwright/test": "^1.52.0"
  }
}
```

Install with `npx playwright install chromium` for the browser binary.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Flaky drag-and-drop tests | Use generous timeouts, precise coordinates, step-based mouse movement. Mark as `test.slow()` if needed. |
| SSE timing issues | Use Playwright's `waitForSelector` / `toContainText` with timeouts rather than fixed delays. |
| Port conflicts in CI | `reuseExistingServer: true` handles this. Document required ports (5173, 8000, 5432). |
| Test data pollution | Each test file creates its own project. No shared state between files. |
| Slow test suite | Start with Chromium only. Run in CI separately from quality gate. Optimize later with parallelism per test file if needed. |
| Frontend components lack test selectors | Add `data-testid` as needed during implementation. Prefer semantic selectors first. |

## Out of Scope

- Cross-browser testing (Firefox, WebKit) — add later
- Visual regression testing (screenshot comparison) — future feature
- Performance/load testing
- Mobile viewport testing
- Authentication flows (dashboard is public)
- Agent-facing API testing (covered by existing pytest tests)
