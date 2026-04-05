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

If you are working in a worktree (`wt-*` branch), you MUST only touch files in your assigned context. The directory mappings are defined in `scripts/create-worktree.sh` — that is the source of truth.

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
make contract-check   # Validate backend matches API contract
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
- **Run all tests FIRST, before writing any code.** Establish a green baseline so you know any failures are caused by your changes, not pre-existing issues.
- **Before adding a dependency, check what's already installed.** Search `package.json` / `pyproject.toml` first. If the dependency is already used elsewhere, check how existing tests handle it — don't add unnecessary mocks or workarounds.
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

### Cross-Context Integration
- **Router registration:** If your context has `routes.py`, it MUST be registered in `src/gateway/app.py` via `app.include_router()`. If you can't edit `app.py` due to worktree discipline, add a comment at the top of your routes.py noting it needs registration, and mention it in your PR description.
- **Alembic migrations:** Your migration's `down_revision` must point to the latest existing migration, not just the one that existed when your worktree branched. If another context merged a migration before you, rebase and update your `down_revision` before pushing. Check with `python -m alembic history`.
- **Auth consistency:** All agent-facing endpoints use `Authorization: Bearer <api-key>`. Dashboard-facing endpoints are public (no auth). Never use query parameters for auth. Use the `CurrentProject` dependency from `src/gateway/auth.py`.
- **Model imports in tests:** All model classes must be imported in `tests/conftest.py` so `Base.metadata.create_all` creates all tables. If you add a new model, verify the import exists.

### Planning Before Implementation
- **Never create implementation tasks without going through the planning pipeline first.** The pipeline is: design spec (brainstorming) → API contract (DDD architect + reviewer) → implementation plan → then create tasks and execute.
- Features on the board represent work to be planned, not pre-decomposed task lists. The implementation tasks emerge from the planning process.
- If you need to note a feature idea, create the feature on the board but leave it empty. The planning pipeline fills in the tasks.

### Execution Workflow (Mandatory)
- **Always use subagent-driven development** — never ask which execution approach; subagent-driven is always the choice.
- **After writing an implementation plan, before dispatching any subagent:**
  1. Register with cloglog via `register_agent` MCP tool (if not already registered)
  2. Create one board task per plan task using `create_task` MCP tool under the correct feature
  3. For each task: call `start_task` before dispatching the subagent, call `complete_task` after it finishes
- This is non-negotiable. The board must reflect what is being worked on in real-time. Never batch-implement without tracking on the board.

### API Contract Enforcement
- **Every wave must have an API contract** designed before worktrees launch. The contract is an OpenAPI YAML file at `docs/contracts/<wave-name>.openapi.yaml`.
- The contract is designed by the DDD Architect agent and reviewed by the DDD Reviewer agent during the planning phase. These agents enforce DDD principles: aggregate boundaries, ubiquitous language, context boundary respect, and consumer sufficiency.
- **Frontend worktrees**: Import API types from `generated-types.ts` (auto-generated from the contract). NEVER hand-write API response types.
- **Backend worktrees**: Implement endpoints matching the contract exactly. Run `make contract-check` before committing.
- If you need to change the API shape, STOP and update the contract first — don't work around it.
- `make quality` validates contract compliance automatically. Your commit will be blocked if your implementation drifts from the contract.

### Worktree Hygiene
- **Never commit CONTRACT.yaml.** It's a local reference file copied by `create-worktree.sh`. It is in `.gitignore`.
- **Task lifecycle in worktrees:** Move tasks through `in_progress → review` using `update_task_status` MCP tool. Before moving to review, add a structured test report via `add_task_note` covering: (1) **Pre-existing tests** — how many existed, were any affected? (2) **Modified tests** — which tests changed and why? (3) **New tests** — what was added, what edge cases covered? (4) **Testing strategy** — why these tests, what risks considered? (5) **Results** — final pass/fail with clear delta (e.g., "3 modified, 1 new, 0 removed"). This is a demo of your testing judgment, not just a pass count.
- **PR merge detection:** After creating a PR and starting a `/loop`, check `gh pr view --json state` to detect when the PR is merged. When merged: mark all tasks as done via `complete_task`, call `unregister_agent`, then exit cleanly.
- **SSE events are live:** The board updates in real-time via SSE. When you change task status, the dashboard reflects it immediately.

---

*This section is updated after each wave with learnings from PR reviews. If you encounter a new pattern that future agents should know, note it in your PR description so it can be added here.*

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
