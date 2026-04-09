# Design Spec: E2E Tests in CI Pipeline (F-29)

**Date:** 2026-04-09
**Status:** Draft
**Feature:** F-29 — E2E Tests in CI Pipeline

## Problem

Agents can merge PRs that break integration points because there is no CI pipeline. The quality gate (`make quality`) runs locally via a Claude Code hook, but nothing enforces it on GitHub. A red CI check on PRs would catch breakage before merge.

## Goals

1. Run the full quality gate on every PR with source changes
2. Catch integration breakage before merge, not after
3. Keep CI fast enough that agents don't stall waiting (target: <5 min)
4. Notify the agent that opened the PR when CI fails so it can self-heal

## Non-Goals

- Playwright browser E2E in CI (requires headed Chrome; add later with `playwright install --with-deps chromium`)
- Deployment pipelines
- Performance/load testing

---

## 1. GitHub Actions Workflow

### File: `.github/workflows/ci.yml`

**Trigger:** `pull_request` events (`opened`, `synchronize`, `reopened`) targeting `main`.

### Job Structure

```
ci:
  ├── Setup PostgreSQL (service container)
  ├── Checkout code
  ├── Setup Python 3.12 + uv
  ├── Setup Node 22 + npm ci (frontend + MCP server)
  ├── Install Python deps (uv sync --all-extras)
  ├── Run Alembic migrations
  ├── Lint (ruff check + ruff format --check)
  ├── Typecheck (mypy)
  ├── Backend tests + coverage (pytest --cov)
  ├── Frontend tests (cd frontend && npx vitest run)
  ├── MCP server tests (cd mcp-server && npm test)
  ├── Contract check (make contract-check)
  └── Upload test artifacts on failure
```

Single job, not a matrix — the steps are sequential and share the database. A single job avoids paying the container startup cost multiple times and keeps the workflow simple.

### PostgreSQL Service Container

```yaml
services:
  postgres:
    image: postgres:16-alpine
    env:
      POSTGRES_USER: cloglog
      POSTGRES_PASSWORD: cloglog_dev
      POSTGRES_DB: cloglog
    ports:
      - 5432:5432
    options: >-
      --health-cmd "pg_isready -U cloglog"
      --health-interval 5s
      --health-timeout 3s
      --health-retries 10
```

This matches the local `docker-compose.yml` exactly — same image, same credentials, same database name. Tests connect to `localhost:5432` just like local development.

### Python + uv Setup

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: '3.12'

- uses: astral-sh/setup-uv@v4

- run: uv sync --all-extras
```

### Node Setup (for frontend + MCP server)

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: '22'
    cache: 'npm'
    cache-dependency-path: |
      frontend/package-lock.json
      mcp-server/package-lock.json

- run: cd frontend && npm ci
- run: cd mcp-server && npm ci
```

### Database Migration

```yaml
- run: uv run alembic upgrade head
```

This runs against the service container's `cloglog` database. The test conftest creates its own ephemeral `cloglog_test_<uuid>` database per test session, cloned from this schema.

### Test Steps

```yaml
- name: Lint
  run: uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/

- name: Typecheck
  run: uv run mypy src/

- name: Backend tests
  run: uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80 -v --tb=short

- name: Frontend tests
  run: cd frontend && npx vitest run

- name: MCP server tests
  run: cd mcp-server && npm test

- name: Contract check
  run: make contract-check
```

### Artifact Upload on Failure

```yaml
- uses: actions/upload-artifact@v4
  if: failure()
  with:
    name: test-results
    path: |
      htmlcov/
      frontend/coverage/
```

---

## 2. Smart Triggering (Path Filters)

### Approach: `paths` filter on the workflow trigger

```yaml
on:
  pull_request:
    branches: [main]
    paths:
      - 'src/**'
      - 'frontend/src/**'
      - 'frontend/package.json'
      - 'frontend/package-lock.json'
      - 'frontend/tsconfig*.json'
      - 'frontend/vite.config.ts'
      - 'frontend/vitest.config.ts'
      - 'mcp-server/src/**'
      - 'mcp-server/package.json'
      - 'mcp-server/package-lock.json'
      - 'mcp-server/tsconfig.json'
      - 'tests/**'
      - 'pyproject.toml'
      - 'uv.lock'
      - 'Makefile'
      - 'alembic/**'
      - 'alembic.ini'
      - '.github/workflows/ci.yml'
```

### What triggers CI

| Path | Why |
|------|-----|
| `src/**` | Backend source changes |
| `frontend/src/**` | Frontend source changes |
| `frontend/package*.json` | Dependency changes affect build/test |
| `mcp-server/src/**`, `mcp-server/package*.json` | MCP tool changes |
| `tests/**` | Test changes (including E2E) |
| `pyproject.toml`, `uv.lock` | Python dependency changes |
| `Makefile` | Build/quality targets |
| `alembic/**`, `alembic.ini` | Migration changes |
| `.github/workflows/ci.yml` | CI config itself |

### What skips CI

| Path | Why |
|------|-----|
| `docs/**` | Documentation only |
| `CLAUDE.md`, `.claude/**` | Agent configuration |
| `scripts/**` | Local tooling scripts |
| `*.md` (root level) | README, CHANGELOG, etc. |
| `docs/demos/**` | Demo artifacts |

### Edge Cases

**`Makefile` changes:** Included because `make quality` is the CI target — a broken Makefile breaks CI.

**`pyproject.toml` changes:** Included because dependency additions/removals and test config changes (`[tool.pytest]`) directly affect test results.

**`frontend/vite.config.ts`:** Included because Vite config changes affect the build and could break tests.

---

## 3. Test Infrastructure in CI

### Database Lifecycle

1. **GitHub Actions service container** starts PostgreSQL 16 with `cloglog` database
2. **Alembic migrations** run against `cloglog` to create the schema
3. **`tests/conftest.py`** creates a unique `cloglog_test_<uuid>` database per test session using `asyncpg.connect` → `CREATE DATABASE`
4. **`tests/e2e/conftest.py`** creates its own test client pointing at a unique test DB
5. After tests complete, conftest tears down the test databases

This existing pattern works in CI without modification — the only prerequisite is a running PostgreSQL with the `cloglog` user.

### No Server Startup Needed for Backend Tests

The backend tests (including E2E API tests in `tests/e2e/`) use `httpx.AsyncClient` with `ASGITransport` — they don't need a running uvicorn server. The ASGI app is tested in-process. This is fast and reliable.

### Frontend Tests

Vitest runs with `jsdom` — no browser needed. `cd frontend && npx vitest run` works in CI.

### MCP Server Tests

Node-based, no external dependencies. `cd mcp-server && npm test` works in CI.

### Playwright Browser Tests — Deferred

Playwright tests (`tests/e2e/playwright/`) require:
- A running backend server (uvicorn)
- A running frontend dev server (vite)
- Chromium installed (`npx playwright install --with-deps chromium`)

These add ~2 minutes of setup and are more fragile in CI. **Recommendation: defer to a follow-up PR.** The API-level E2E tests in `tests/e2e/test_*.py` already cover cross-context integration. Playwright tests add UI regression coverage, which is valuable but not the first priority for CI.

When added later, Playwright tests should run as a separate job that depends on the main CI job passing first, to avoid wasting compute on browser tests when unit tests fail.

---

## 4. Agent Notification on CI Failure

### Current Agent Polling Loop

Agents already poll for PR comments and merge state using:
```bash
gh pr view <PR_NUM> --json state -q .state
gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/comments
gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments
gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/reviews
```

### Adding CI Status Checks

Agents should add one more check to their poll loop:

```bash
# Check CI status for the PR
gh pr checks <PR_NUM> --json name,state,conclusion
```

Or more specifically:

```bash
# Get the CI workflow run status
gh run list --branch <BRANCH> --workflow ci.yml --json status,conclusion -L 1
```

### Failure Recovery Flow

1. Agent's `/loop` detects CI failure via `gh pr checks`
2. Agent reads the CI logs:
   ```bash
   # Find the failed run
   RUN_ID=$(gh run list --branch <BRANCH> --workflow ci.yml -L 1 --json databaseId -q '.[0].databaseId')
   # Read the logs
   gh run view $RUN_ID --log-failed
   ```
3. Agent diagnoses the failure from the log output
4. Agent pushes a fix commit
5. CI re-triggers automatically (the `synchronize` event fires on push)

### Integration with Existing PR Comment Polling

The CI check should be added to the CLAUDE.md agent learnings section under "PR polling." The poll commands become:

```bash
# 1. Check merge state
gh pr view <PR_NUM> --json state -q .state
# 2. Check CI status (NEW)
gh pr checks <PR_NUM> --json name,state,conclusion
# 3. Check for inline review comments
gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/comments --jq '...'
# 4. Check for issue-style comments
gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments --jq '...'
# 5. Check for review state
gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/reviews --jq '...'
```

### When CI Is Still Running

If `gh pr checks` shows `IN_PROGRESS`, the agent should skip the CI check and continue polling normally. Don't stall waiting for CI — check again on the next loop iteration.

---

## 5. Required vs Advisory

### Recommendation: **Required** (block merge on failure)

| Option | Pros | Cons |
|--------|------|------|
| **Required** | Prevents broken code from reaching main; agents must fix CI before merge | Blocks merge if CI has flaky tests |
| **Advisory** | Never blocks a legitimate merge; agents can override | Defeats the purpose — agents will ignore failures |

**Why required:** The whole point of CI is to prevent breakage. Agents are autonomous — they won't voluntarily delay a merge unless forced. Making CI advisory means it provides information but no enforcement, and agents that are eager to complete tasks will merge anyway.

**Mitigations for flaky tests:**
- The quality gate already has coverage thresholds and strict linting — tests that pass locally should pass in CI
- If a test is genuinely flaky (not a code bug), mark it `@pytest.mark.xfail(reason="...")` with a tracking issue
- Add a re-run button: `gh run rerun $RUN_ID` for transient infrastructure failures

### GitHub Branch Protection Setup

```
Settings → Branches → main:
  ✅ Require status checks to pass before merging
  ✅ Require branches to be up to date before merging
  Status checks: "ci" (the workflow job name)
```

---

## 6. Pre-existing Test Failures

### Current State

The prompt mentions 5 failing tests related to `complete_task`. These need to be resolved before CI is useful, because required CI would block all merges.

### Strategy: Fix Before Enabling Required CI

1. **Diagnose the failures** — run `uv run pytest tests/ -v --tb=long -k complete_task` locally
2. **Fix the root cause** if it's a real bug
3. **Mark as `xfail` with a ticket** if the feature is intentionally not yet implemented:
   ```python
   @pytest.mark.xfail(reason="T-XXX: complete_task guard not yet implemented")
   ```
4. **Enable required CI** only after all tests pass or are properly marked

This should be a separate task (T-xxx) that runs before the CI workflow PR is merged. The implementation plan will sequence it appropriately.

### CI Should Never Start With Known Failures

Starting CI with known failures teaches agents to ignore CI results. If CI is red from day one, no one trusts it. Fix first, then enable.

---

## 7. What Tests Run in CI

### Full Quality Gate

CI should run `make quality` (or its equivalent steps), which includes:

| Step | Command | What It Catches |
|------|---------|----------------|
| Lint | `ruff check + ruff format --check` | Style violations, import issues |
| Typecheck | `mypy src/` | Type errors |
| Backend tests + coverage | `pytest tests/ --cov --cov-fail-under=80` | Logic bugs, regressions, coverage drops |
| Contract check | `make contract-check` | API drift from OpenAPI contracts |

Plus additional steps not in `make quality`:

| Step | Command | What It Catches |
|------|---------|----------------|
| Frontend tests | `cd frontend && npx vitest run` | Component regressions |
| MCP server tests | `cd mcp-server && npm test` | Tool registration/plumbing bugs |

### Why Not Just `make quality`?

`make quality` only covers backend. CI should test the full stack. The frontend and MCP server have their own test suites that aren't included in `make quality` today.

### Future Addition: Playwright E2E

When added (separate PR), Playwright tests would run as a second job:

```yaml
jobs:
  ci:
    # ... existing quality gate
  
  e2e-browser:
    needs: ci
    # ... Playwright setup + tests
```

This ensures browser tests only run after the fast checks pass.

---

## 8. Caching Strategy

### Python Dependencies

```yaml
- uses: astral-sh/setup-uv@v4
  with:
    enable-cache: true
```

uv's built-in caching handles this. The `setup-uv` action caches the uv store between runs.

### Node Dependencies

```yaml
- uses: actions/setup-node@v4
  with:
    cache: 'npm'
    cache-dependency-path: |
      frontend/package-lock.json
      mcp-server/package-lock.json
```

npm's cache is keyed on the lock files. Cache invalidates only when dependencies change.

### Expected CI Time

| Step | Estimated Time |
|------|---------------|
| Checkout + setup | 15s |
| PostgreSQL ready | 5s |
| uv sync (cached) | 10s |
| npm ci × 2 (cached) | 15s |
| Alembic migration | 3s |
| Lint | 5s |
| Typecheck | 10s |
| Backend tests | 30s |
| Frontend tests | 15s |
| MCP tests | 10s |
| Contract check | 5s |
| **Total** | **~2 min** |

Well under the 5-minute target.

---

## 9. Workflow YAML Skeleton

```yaml
name: CI

on:
  pull_request:
    branches: [main]
    paths:
      - 'src/**'
      - 'frontend/src/**'
      - 'frontend/package.json'
      - 'frontend/package-lock.json'
      - 'frontend/tsconfig*.json'
      - 'frontend/vite.config.ts'
      - 'frontend/vitest.config.ts'
      - 'mcp-server/src/**'
      - 'mcp-server/package.json'
      - 'mcp-server/package-lock.json'
      - 'mcp-server/tsconfig.json'
      - 'tests/**'
      - 'pyproject.toml'
      - 'uv.lock'
      - 'Makefile'
      - 'alembic/**'
      - 'alembic.ini'
      - '.github/workflows/ci.yml'

concurrency:
  group: ci-${{ github.head_ref }}
  cancel-in-progress: true

jobs:
  ci:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_USER: cloglog
          POSTGRES_PASSWORD: cloglog_dev
          POSTGRES_DB: cloglog
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U cloglog"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'
          cache-dependency-path: |
            frontend/package-lock.json
            mcp-server/package-lock.json

      - name: Install Python dependencies
        run: uv sync --all-extras

      - name: Install frontend dependencies
        run: cd frontend && npm ci

      - name: Install MCP server dependencies
        run: cd mcp-server && npm ci

      - name: Run database migrations
        run: uv run alembic upgrade head

      - name: Lint
        run: uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/

      - name: Typecheck
        run: uv run mypy src/

      - name: Backend tests
        run: uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80 -v --tb=short

      - name: Frontend tests
        run: cd frontend && npx vitest run

      - name: MCP server tests
        run: cd mcp-server && npm test

      - name: Contract check
        run: make contract-check

      - name: Upload test artifacts
        uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: test-results
          path: |
            htmlcov/
            frontend/coverage/
          retention-days: 7
```

---

## 10. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Single job vs matrix | Single job | Steps share DB; avoids redundant container startup |
| Required vs advisory | Required | Agents are autonomous; advisory provides no enforcement |
| Playwright in v1 | Deferred | API-level E2E covers integration; browser tests add setup complexity |
| Path filters | On trigger | Simpler than job-level `if` conditions; GitHub handles it natively |
| Concurrency | Cancel in-progress | Agent pushes fix → old run should stop immediately |
| Fix failures first | Yes | CI that starts red is CI no one trusts |
| Frontend + MCP in CI | Yes | Full stack coverage, not just backend |

---

## 11. Implementation Sequence

1. **Fix pre-existing test failures** (separate task, prerequisite)
2. **Create `.github/workflows/ci.yml`** with the workflow above
3. **Update CLAUDE.md** — add CI polling commands to agent learnings
4. **Enable branch protection** on `main` requiring the `ci` check
5. **Follow-up: Playwright job** (separate feature/task)
