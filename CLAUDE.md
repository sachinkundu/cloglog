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

For the full context map, relationship types, and ubiquitous language glossary, see `docs/ddd-context-map.md`.

## Worktree Discipline

If you are working in a worktree, you MUST only touch files in your assigned context:

- `wt-board` → `src/board/`, `tests/board/`
- `wt-agent` → `src/agent/`, `tests/agent/`
- `wt-document` → `src/document/`, `tests/document/`
- `wt-gateway` → `src/gateway/`, `tests/gateway/`
- `wt-frontend` → `frontend/`
- `wt-mcp` → `mcp-server/`

Do NOT modify files outside your assigned directories. If you need a change in another context, note it and coordinate.

**This is enforced by a Claude Code hook** (`.claude/hooks/protect-worktree-writes.sh`). Writes to files outside your assigned directories will be blocked automatically.

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

**This is enforced by a Claude Code hook** (`.claude/hooks/quality-gate-before-commit.sh`). Any `git commit`, `git push`, or `gh pr create` will automatically run `make quality` first and block if it fails.

## Git Identity & PRs

**All pushes and PRs MUST use the GitHub App bot identity, never the user's personal identity.**

To push and create PRs:

```bash
# Get a bot token (valid for ~1 hour)
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)

# Push using the bot token
git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/sachinkundu/cloglog.git"
git push -u origin HEAD

# Create PR as the bot
GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "..."
```

Never use `git push` or `gh pr create` without first setting the bot token. The user cannot merge their own PRs — all agent work must appear as authored by the bot.

## Agent Learnings

Hard-won lessons from previous waves. Every agent in every worktree MUST follow these.

### Testing
- **Every PR must include automated tests.** No exceptions. If you write code, you write tests for it.
- Frontend work requires component tests (@testing-library/react), not just "it renders" smoke tests. Test interactions, conditional rendering, error states.
- Backend work requires both unit tests (business logic) and integration tests (API endpoints against real DB).
- PRs without tests will be rejected in review.

### PR Quality
- Every PR must include a **Test Report** section showing: what tests were added, test output, coverage.
- Frontend PRs should include screenshots of the UI.
- Run the full quality gate (`make quality`) before pushing. Don't assume it passes.

### Git Identity
- NEVER push or create PRs as the user. Always use the bot identity. See "Git Identity & PRs" section above.
- If you're unsure whether you're pushing as the bot, check `git remote -v` after setting the URL.

---

*This section is updated after each wave with learnings from PR reviews. If you encounter a new pattern that future agents should know, note it in your PR description so it can be added here.*

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
