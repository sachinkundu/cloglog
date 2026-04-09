# F-29: E2E Tests in CI Pipeline — Implementation Plan

**Date:** 2026-04-09
**Spec:** `docs/superpowers/specs/2026-04-09-ci-e2e-pipeline.md`

## Pre-requisite: Fix Pre-existing Test Failures

Before implementing the CI workflow, all tests must pass. Run `uv run pytest tests/ -v --tb=long -k complete_task` to identify the 5 failing tests. Either fix the root cause or mark with `@pytest.mark.xfail(reason="T-XXX: ...")`. CI that starts red is CI no one trusts.

**Verify:** `uv run pytest tests/ -v --tb=short` — all tests pass (0 failures, 0 errors).

## Implementation Steps

### Step 1: Create the CI workflow file

**Files to create:**
- `.github/workflows/ci.yml`

**Actions:**
1. Create `.github/workflows/` directory
2. Write `ci.yml` with two jobs: `ci` (fast) and `e2e-browser` (slow, depends on `ci`)

**`ci` job contents:**
- `runs-on: ubuntu-latest`
- PostgreSQL 16 service container (user: `cloglog`, password: `cloglog_dev`, db: `cloglog`)
- `actions/checkout@v4`
- `actions/setup-python@v5` with python 3.12
- `astral-sh/setup-uv@v4` with `enable-cache: true`
- `actions/setup-node@v4` with node 22, npm cache keyed on `frontend/package-lock.json` + `mcp-server/package-lock.json`
- `uv sync --all-extras`
- `cd frontend && npm ci`
- `cd mcp-server && npm ci`
- `uv run alembic upgrade head`
- Lint: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`
- Typecheck: `uv run mypy src/`
- Backend tests: `uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80 -v --tb=short`
- Frontend tests: `cd frontend && npx vitest run`
- MCP server tests: `cd mcp-server && npm test`
- Contract check: `make contract-check`
- Upload `htmlcov/` and `frontend/coverage/` as artifacts on failure (7-day retention)

**`e2e-browser` job contents:**
- `needs: ci`
- Same PostgreSQL service container
- Check if browser tests needed: `gh pr diff --name-only`, grep for `frontend/`, `src/gateway/`, `tests/e2e/playwright/`; set output flag `run=true|false`
- All subsequent steps gated on `if: steps.check.outputs.run == 'true'`
- Same Python/Node/uv setup
- `cd frontend && npm ci` + `cd tests/e2e/playwright && npm ci`
- `npx playwright install --with-deps chromium`
- `uv run alembic upgrade head`
- `cd tests/e2e/playwright && npx playwright test` with env `BACKEND_PORT=8001`, `FRONTEND_PORT=5174`
- Upload `tests/e2e/playwright/test-results/` and `tests/e2e/playwright/playwright-report/` as artifacts on failure (14-day retention)

**Workflow-level settings:**
- Trigger: `pull_request` on `main` with path filters (see spec Section 2)
- Concurrency: `group: ci-${{ github.head_ref }}`, `cancel-in-progress: true`

**Verify:** Push a test branch with a source file change, verify the workflow triggers and both jobs run on GitHub Actions.

### Step 2: Update CLAUDE.md with CI polling commands

**Files to modify:**
- `CLAUDE.md` — Agent Learnings → PR polling section

**Actions:**
1. Add CI status check command to the PR polling block:
   ```bash
   # Check CI status (NEW)
   gh pr checks <PR_NUM> --json name,state,conclusion
   ```
2. Add a new subsection under Agent Learnings: "CI Failure Recovery"
   - How to detect CI failure: `gh pr checks` shows `FAILURE`
   - How to read logs: `gh run list --branch <BRANCH> --workflow ci.yml -L 1 --json databaseId`, then `gh run view $RUN_ID --log-failed`
   - Agent pushes fix → `synchronize` event re-triggers CI automatically
   - If CI is `IN_PROGRESS`, skip and check again next poll iteration

**Verify:** Read CLAUDE.md and confirm the new commands are in the correct section.

### Step 3: Verify CI end-to-end

**Actions:**
1. Create a PR with the workflow file and CLAUDE.md changes
2. The PR itself should trigger CI (since `.github/workflows/ci.yml` is in the path filter)
3. Verify:
   - `ci` job runs: lint, typecheck, backend tests, frontend tests, MCP tests, contract check all pass
   - `e2e-browser` job runs (or skips correctly if no frontend changes)
   - Concurrency works: pushing a fix commit cancels the in-progress run
4. Check that `gh pr checks` correctly shows the CI status

**Verify:** CI passes green on the PR. Both jobs complete successfully.

## Files Changed Summary

| File | Action | Description |
|------|--------|-------------|
| `.github/workflows/ci.yml` | Create | CI workflow with `ci` + `e2e-browser` jobs |
| `CLAUDE.md` | Modify | Add CI polling + failure recovery to agent learnings |

## Post-Implementation

After the CI workflow PR merges:
- Enable branch protection on `main` requiring the `ci` status check (manual step — requires repo admin)
- Optionally require `e2e-browser` as well, or leave it advisory initially

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Flaky tests block all merges | Mark genuinely flaky tests `xfail` with tracking issue |
| Playwright install slow | Cached after first run; ~45s even uncached |
| Service container startup | Health check with retries; 10s typical |
| Path filter too narrow | Include `.github/workflows/ci.yml` so CI config changes trigger CI |
| Path filter too broad | Only source, test, config, and dependency files included |
