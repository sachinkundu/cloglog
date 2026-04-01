# CLAUDE.md — cloglog

## Project Overview

cloglog is a multi-project Kanban dashboard for managing autonomous AI coding agents running in agent-vm sandboxes.

## Architecture

DDD bounded contexts — each context owns its own models, services, repository, and routes:

- **Board** (`src/board/`) — Projects, Epics, Features, Tasks, status roll-up
- **Agent** (`src/agent/`) — Worktrees, Sessions, registration, heartbeat
- **Document** (`src/document/`) — Append-only document storage
- **Gateway** (`src/gateway/`) — API composition, auth, SSE, CLI

Contexts communicate through interfaces defined in `interfaces.py`, never by importing each other's internals.

## Worktree Discipline

If you are working in a worktree, you MUST only touch files in your assigned context:

- `wt-board` → `src/board/`, `tests/board/`
- `wt-agent` → `src/agent/`, `tests/agent/`
- `wt-document` → `src/document/`, `tests/document/`
- `wt-gateway` → `src/gateway/`, `tests/gateway/`
- `wt-frontend` → `frontend/`
- `wt-mcp` → `mcp-server/`

Do NOT modify files outside your assigned directories. If you need a change in another context, note it and coordinate.

## Commands

```bash
make quality          # Full quality gate — must pass before completing any task
make test             # All backend tests
make test-board       # Board context tests only
make test-agent       # Agent context tests only
make test-document    # Document context tests only
make test-gateway     # Gateway context tests only
make lint             # Ruff linter
make typecheck        # mypy type checking
make run-backend      # Start FastAPI dev server
make db-up            # Start PostgreSQL via Docker Compose
make db-migrate       # Run Alembic migrations
```

## Quality Gate

Before completing any task or creating a PR, run `make quality` and verify it passes.

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
