# AGENTS.md — cloglog

Shared instructions for all AI coding agents (Claude Code, Codex, etc.).
For Claude Code-specific instructions, see CLAUDE.md.

## Project architecture

Python/FastAPI + React/TypeScript monorepo using Domain-Driven Design.

### Bounded contexts (DO NOT cross-import)

| Context   | Directory        | Owns                                    |
|-----------|------------------|-----------------------------------------|
| Board     | `src/board/`     | Projects, Epics, Features, Tasks        |
| Agent     | `src/agent/`     | Worktrees, Sessions, registration       |
| Document  | `src/document/`  | Append-only document storage            |
| Gateway   | `src/gateway/`   | API composition, auth, SSE, webhooks    |

Contexts communicate through `interfaces.py`, never by importing each other's internals.

## Review guidelines

<!-- Read by Codex CLI during automated PR reviews -->

- Focus on correctness and security; ignore style/formatting (ruff handles that)
- Cross-context imports (board/, agent/, document/, gateway/) are DDD boundary violations — priority 3
- All API endpoints must match OpenAPI contracts in `docs/contracts/`
- Pydantic Update schemas must include all fields the endpoint accepts (`model_dump(exclude_unset=True)` silently drops unrecognized fields) — priority 2
- `raise HTTPException` inside `except` blocks must use `raise ... from None` (ruff B904)
- Auth: agent-facing endpoints use Bearer token; dashboard endpoints are public; webhook endpoint uses HMAC
- Never hardcode ports — use environment variables from `.env`
- All model classes must be imported in `tests/conftest.py` for `Base.metadata.create_all`
- Frontend must import API types from `generated-types.ts`, never hand-write them
- Do not flag pre-existing issues in unchanged code
- If the patch is correct, say so — do not invent problems

## Testing requirements

- Backend tests use real PostgreSQL, no mocks
- Frontend tests use @testing-library/react patterns
- E2E tests create their own isolated database and servers
- Run `make quality` before any PR

## Tech stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Linting: ruff, mypy
- Testing: pytest, Vitest, Playwright
