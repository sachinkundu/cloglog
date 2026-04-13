# CLAUDE.md — cloglog

## Project Overview

cloglog is a multi-project Kanban dashboard for managing autonomous AI coding agents running in agent-vm sandboxes.

**This project uses the cloglog plugin** (`plugins/cloglog/`) for workflow discipline — planning pipeline, PR workflow, agent lifecycle, and worktree management. Generic workflow rules are provided by the plugin. This file contains cloglog-specific instructions.

## Architecture

DDD bounded contexts — each context owns its own models, services, repository, and routes:

- **Board** (`src/board/`) — Projects, Epics, Features, Tasks, status roll-up
- **Agent** (`src/agent/`) — Worktrees, Sessions, registration, heartbeat
- **Document** (`src/document/`) — Append-only document storage
- **Gateway** (`src/gateway/`) — API composition, auth, SSE, CLI

Contexts communicate through interfaces defined in `interfaces.py`, never by importing each other's internals.

For the full context map, relationship types, and ubiquitous language glossary, see `docs/ddd-context-map.md`.

## Worktree Discipline

If you are working in a worktree (`wt-*` branch), you MUST only touch files in your assigned context. The directory mappings are defined in `.cloglog/config.yaml` under `worktree_scopes`.

Do NOT modify files outside your assigned directories. If you need a change in another context, note it and coordinate.

**This is enforced by the cloglog plugin's `protect-worktree-writes` hook.** Writes to files outside your assigned directories will be blocked automatically.

## Commands

```bash
make quality          # Full quality gate — must pass before completing any task
make test             # All backend tests
make test-board       # Board context tests only
make test-agent       # Agent context tests only
make test-document    # Document context tests only
make test-gateway     # Gateway context tests only
make test-e2e         # Backend E2E integration tests (pytest)
make test-e2e-browser # Playwright browser E2E tests (headless)
make lint             # Ruff linter
make typecheck        # mypy type checking
make run-backend      # Start FastAPI dev server
make dev              # Start both backend + frontend dev servers
make db-up            # Start PostgreSQL via Docker Compose
make db-down          # Stop PostgreSQL
make db-migrate       # Run Alembic migrations
make db-revision      # Create new Alembic migration
make contract-check   # Validate backend matches API contract
make coverage         # Run tests with coverage report
```

### Frontend

```bash
cd frontend && make test    # Frontend tests (Vitest)
cd frontend && make lint    # TypeScript type check
cd frontend && npm run dev  # Start Vite dev server
```

### MCP Server

```bash
cd mcp-server && make test   # MCP server tests
cd mcp-server && make build  # Build TypeScript
```

## Environment Quirks

- **Run frontend tests from `frontend/` directory:** `cd frontend && npx vitest run`. Running from repo root causes `document is not defined` errors.
- **Run backend tests from repo root:** `uv run pytest` from `/home/sachin/code/cloglog`.

## Quality Gate

Before completing any task or creating a PR, run `make quality` and verify it passes.

**This is enforced by the cloglog plugin's `quality-gate` hook.** Any `git commit`, `git push`, or `gh pr create` will automatically run the quality command first and block if it fails.

## Git Identity & PRs

**All pushes, PRs, and GitHub API calls MUST use the GitHub App bot identity.** Use the `github-bot` skill for all GitHub operations — it has the exact commands for pushing, creating PRs, checking PR status, replying to comments, and CI recovery. Never use `git push`, `gh pr`, or `gh api` without the bot token.

## Non-Negotiable Principles

These are CRITICAL. Every agent, every worktree, every task. No exceptions.

1. **Always choose the best option, not the easiest.** When proposing approaches, pick the architecturally sound solution even if it requires more work. Never take shortcuts that create tech debt. The right solution now saves pain later.

2. **Boy Scout Rule: leave the code better than you found it.** Fix pre-existing problems before adding new code. If you find broken tests, fix them first. If you find inconsistent naming, fix it. If you find a bug in code you're touching, fix it. Never pile new work on top of existing problems.

## Project-Specific Agent Instructions

These instructions are specific to cloglog's architecture and tech stack. They supplement the generic workflow rules provided by the cloglog plugin.

### Spec Phase — DDD Contract Design
- For features that add or modify API endpoints, spawn the `ddd-architect` agent to design the API contract following DDD principles (aggregate boundaries, ubiquitous language, context boundary respect).
- Spawn the `ddd-reviewer` agent to review the contract. Allow up to 3 revision rounds.
- The contract is an OpenAPI YAML file at `docs/contracts/<wave-name>.openapi.yaml`.

### Implementation Phase — Subagents
- **Spawn `test-writer`** for writing tests. It carries codified testing standards (real DB, no mocks, @testing-library/react patterns, coverage requirements). See `.claude/agents/test-writer.md`.
- **Spawn `migration-validator`** when touching database models. It validates Alembic migration files (revision chain, upgrade/downgrade, model imports).
- **Frontend worktrees need `cd frontend && npm install`** before tests will run — node_modules are not shared across worktrees.

### Pydantic Schema Gotcha
- **When adding a field to an API update call, verify the Pydantic schema includes it.** `model_dump(exclude_unset=True)` silently drops fields not in the schema — the API returns 200 but nothing is saved. No error, no warning. Always grep for the `XUpdate` model and confirm the field exists before assuming the API will persist it.

### Debugging Persistence Bugs
- **Check the DB before writing code.** For any "X doesn't persist on refresh" bug: (1) check DB state, (2) reproduce the action, (3) check DB again. If unchanged -> write path is broken. If changed -> read/render path is broken. One query narrows the problem instantly.
- **Restart Vite for structural changes.** New imports, new components, JSX restructuring — restart the dev server. HMR silently fails on structural changes and the browser keeps running old JavaScript with no visible error.

### Cross-Context Integration
- **Router registration:** If your context has `routes.py`, it MUST be registered in `src/gateway/app.py` via `app.include_router()`. If you can't edit `app.py` due to worktree discipline, add a comment at the top of your routes.py noting it needs registration, and mention it in your PR description.
- **Alembic migrations:** Your migration's `down_revision` must point to the latest existing migration, not just the one that existed when your worktree branched. If another context merged a migration before you, rebase and update your `down_revision` before pushing. Check with `python -m alembic history`.
- **Auth consistency:** All agent-facing endpoints use `Authorization: Bearer <api-key>`. Dashboard-facing endpoints are public (no auth). Never use query parameters for auth. Use the `CurrentProject` dependency from `src/gateway/auth.py`.
- **Concurrent worktree merges:** When multiple worktrees are active, the last to merge faces conflicts in shared files (`events.py`, `schemas.py`, `types.ts`, `package.json`). Plan for this — rebase frequently and resolve conflicts before requesting review.
- **Model imports in tests:** All model classes must be imported in `tests/conftest.py` so `Base.metadata.create_all` creates all tables. If you add a new model, verify the import exists.

### API Contract Enforcement
- **Frontend worktrees**: Import API types from `generated-types.ts` (auto-generated from the contract). NEVER hand-write API response types.
- **Backend worktrees**: Implement endpoints matching the contract exactly. Run `make contract-check` before committing.
- If you need to change the API shape, STOP and update the contract first — don't work around it.
- `make quality` validates contract compliance automatically. Your commit will be blocked if your implementation drifts from the contract.

### Ruff Linting
- **`raise ... from None`** in except clauses — ruff B904 requires this for `raise HTTPException` inside `except` blocks.

### Infrastructure Isolation
- **Each worktree has its own ports and database.** Created by `.cloglog/on-worktree-create.sh`.
- Port assignments are in the worktree's `.env` file. Source `scripts/worktree-ports.sh` for env vars.
- Database is named `cloglog_<worktree_name>` (hyphens replaced with underscores).
- Never hardcode ports. Always use `$BACKEND_PORT`, `$FRONTEND_PORT` from the env.

### Proof-of-Work Demos (cloglog-specific)
- **Backend PRs:** Use Showboat `exec` blocks to curl each new/changed endpoint. Start the backend on your worktree port first.
- **MCP server PRs:** Curl the backend endpoint AND launch a fresh Claude session in a zellij tab to call the actual MCP tool.
- **Frontend PRs:** Use Rodney (headless Chrome via `uvx rodney`) to take screenshots.
- Each worktree runs on isolated ports. Source `scripts/worktree-ports.sh` in demo scripts.

---

*This section is updated after each wave with learnings from PR reviews. If you encounter a new pattern that future agents should know, note it in your PR description so it can be added here.*

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
