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

## Environment Quirks

- **Run frontend tests from `frontend/` directory:** `cd frontend && npx vitest run`. Running from repo root causes `document is not defined` errors.
- **Run backend tests from repo root:** `uv run pytest` from `/home/sachin/code/cloglog`.

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

## Non-Negotiable Principles

These are CRITICAL. Every agent, every worktree, every task. No exceptions.

1. **Always choose the best option, not the easiest.** When proposing approaches, pick the architecturally sound solution even if it requires more work. Never take shortcuts that create tech debt. The right solution now saves pain later.

2. **Boy Scout Rule: leave the code better than you found it.** Fix pre-existing problems before adding new code. If you find broken tests, fix them first. If you find inconsistent naming, fix it. If you find a bug in code you're touching, fix it. Never pile new work on top of existing problems.

## Agent Learnings

Hard-won lessons from previous waves. Every agent in every worktree MUST follow these.

### Testing
- **Run all tests FIRST, before writing any code.** Establish a green baseline so you know any failures are caused by your changes, not pre-existing issues.
- **Before adding a dependency, check what's already installed.** Search `package.json` / `pyproject.toml` first. If the dependency is already used elsewhere, check how existing tests handle it — don't add unnecessary mocks or workarounds.
- **Every PR must include automated tests.** No exceptions. If you write code, you write tests for it.
- Frontend work requires component tests (@testing-library/react), not just "it renders" smoke tests. Test interactions, conditional rendering, error states.
- Backend work requires both unit tests (business logic) and integration tests (API endpoints against real DB).
- PRs without tests will be rejected in review.
- **Frontend worktrees need `cd frontend && npm install`** before tests will run — node_modules are not shared across worktrees.
- **Cross-feature integration tests:** When modifying a component that was recently changed by another feature, write at least one test covering both features together. Check `git log --oneline <file>` to see recent changes. Two features that independently modify the same component can break each other in ways neither feature's tests catch.

### PR Quality
- **PR body structure matters.** The reviewer opens the PR and needs context fast. Use this order:
  1. **Summary** — 1-3 bullets on what and why
  2. **Demo** — immediately after the summary. Embed the demo output (curl responses, screenshots, state machine transitions) directly in the PR body. The reviewer should see proof the feature works before reading any code. Link to the full `demo.md` if it's long, but inline the highlights.
  3. **Test Report** — what tests were added, output, coverage delta
- The demo in the PR body is the most important thing after the summary. It gives the reviewer full context: "this is what the PR does, and here's proof it works." Code review is 10x easier when you already understand what the code is supposed to do.
- Frontend PRs should include screenshots of the UI inline in the PR body.
- Run the full quality gate (`make quality`) before pushing. Don't assume it passes.
- **Proactive rebase:** When other PRs merge to main while yours is open, rebase before the reviewer has to ask.
- **Conflict marker check:** After resolving merge conflicts, run `grep -rn "^<<<<<<" src/ frontend/src/` to catch leftover markers.
- **`raise ... from None`** in except clauses — ruff B904 requires this for `raise HTTPException` inside `except` blocks.

### Git Identity
- NEVER push or create PRs as the user. Always use the bot identity. See "Git Identity & PRs" section above.
- If you're unsure whether you're pushing as the bot, check `git remote -v` after setting the URL.

### Cross-Context Integration
- **Router registration:** If your context has `routes.py`, it MUST be registered in `src/gateway/app.py` via `app.include_router()`. If you can't edit `app.py` due to worktree discipline, add a comment at the top of your routes.py noting it needs registration, and mention it in your PR description.
- **Alembic migrations:** Your migration's `down_revision` must point to the latest existing migration, not just the one that existed when your worktree branched. If another context merged a migration before you, rebase and update your `down_revision` before pushing. Check with `python -m alembic history`.
- **Auth consistency:** All agent-facing endpoints use `Authorization: Bearer <api-key>`. Dashboard-facing endpoints are public (no auth). Never use query parameters for auth. Use the `CurrentProject` dependency from `src/gateway/auth.py`.
- **Concurrent worktree merges:** When multiple worktrees are active, the last to merge faces conflicts in shared files (`events.py`, `schemas.py`, `types.ts`, `package.json`). Plan for this — rebase frequently and resolve conflicts before requesting review.
- **Model imports in tests:** All model classes must be imported in `tests/conftest.py` so `Base.metadata.create_all` creates all tables. If you add a new model, verify the import exists.

### Autonomous Agent Behavior
- **NEVER wait for user input.** Worktree agents are fully autonomous. Make your own design decisions. All communication with the user happens via PR comments on GitHub — never via the terminal.
- **Never use interactive skills that ask questions.** Do not use the brainstorming skill's question-and-answer flow. Write design specs directly with your own recommendations, create the PR, and let the user review it there.
- **Decline visual companion offers.** If a skill offers to show mockups in a browser, decline and include diagrams/mockups as text or markdown in the spec instead.

### Planning Before Implementation
- **Never create implementation tasks without going through the planning pipeline first.** The pipeline is: design spec → implementation plan → then create tasks and execute.
- Features on the board represent work to be planned, not pre-decomposed task lists. The implementation tasks emerge from the planning process.
- If you need to note a feature idea, create the feature on the board but leave it empty. The planning pipeline fills in the tasks.

### Execution Workflow (Mandatory)
- **Always use subagent-driven development** — never ask which execution approach; subagent-driven is always the choice.
- **Every phase of a feature needs a board task** — not just implementation. The full pipeline creates these tasks under the feature via `create_task` MCP tool:
  1. **"Write design spec for F-N"** — move to `review` when spec PR is created, `done` when merged
  2. **"Write implementation plan for F-N"** — move to `review` when plan PR is created, `done` when merged
  3. **"Implement F-N"** — move to `review` when implementation PR is created, `done` when merged
- The notification system fires when tasks move to `review`. Without board tasks, the user gets no notification and doesn't know work is ready for their review.
- For the implementation task, use internal session tasks (TaskCreate/TaskUpdate) to track subagent progress. The board task is the high-level "implementation is done, please review."
- This is non-negotiable. The board must reflect what is being worked on in real-time.

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
- **PR polling — check BOTH comment types and merge state.** GitHub has two kinds of comments: issue-style (`gh pr view --json comments`) and inline review comments on specific lines (`gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/comments`). Reviewers primarily use inline review comments. You MUST check both:
  ```bash
  # Check merge state
  gh pr view <PR_NUM> --json state -q .state
  # Check for inline review comments (this is where most feedback lives)
  gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/comments --jq '.[] | "\(.id) | \(.path):\(.line) | \(.body[:80])"'
  # Check for issue-style PR comments
  gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments --jq '.[] | "\(.id) | \(.body[:80])"'
  # Check for review state (CHANGES_REQUESTED, APPROVED, etc.)
  gh api repos/sachinkundu/cloglog/pulls/<PR_NUM>/reviews --jq '.[] | "\(.state) | \(.body[:80])"'
  ```
  When merged: mark tasks as done via `complete_task`, call `unregister_agent`, then exit cleanly.
- **Reply to every PR comment you address.** When you fix a reviewer's comment, reply directly to that comment on GitHub explaining what you did. The reviewer needs to see at a glance which comments were handled without digging through diffs.
  ```bash
  # Reply to an inline review comment after fixing it
  gh api repos/sachinkundu/cloglog/pulls/comments/<COMMENT_ID>/replies -f body="Fixed — changed X to Y in file.py:42"
  # Reply to an issue-style comment
  gh api repos/sachinkundu/cloglog/issues/<PR_NUM>/comments -f body="Addressed — ..."
  ```
  Do NOT resolve the thread — that's the reviewer's decision. Just reply with what you changed.
- **Attach documents after PR merge:** When a spec or plan PR is merged, attach the document to the feature using `attach_document` MCP tool so it appears on the board card.
- **SSE events are live:** The board updates in real-time via SSE. When you change task status, the dashboard reflects it immediately.
- **Worktree removal:** Use `./scripts/manage-worktrees.sh remove <name>` to remove a single worktree after its PR merges. Use `./scripts/manage-worktrees.sh close <wave-name> <name> [name...]` to close a full wave (generates work log, removes all worktrees, updates main).
- **Zellij tab management:** See `docs/zellij-guide.md` for the complete guide. Key rules: always name tabs after the worktree (`wt-*`), close only tabs you created, close by name→TAB_ID lookup via `zellij action list-tabs`, never by index.

### Agent Shutdown
- **Agents deregister themselves.** When all tasks are complete (`get_my_tasks` returns empty), generate shutdown artifacts and call `unregister-by-path`. Never rely on the master agent or scripts to deregister.
- **All tasks must be assigned before launch.** The master agent must assign all tasks to a worktree before launching the agent. Assign by calling `start_task` or `update_task` with `worktree_id` for each task. The agent exits when its task queue is empty — incremental assignment after launch risks premature exit. Creating tasks on the board is NOT the same as assigning them — tasks without a `worktree_id` won't appear in `get_my_tasks`.
- **Three-tier shutdown:** (1) **Cooperative** — main agent calls `POST /agents/{id}/request-shutdown`, agent sees `shutdown_requested: true` on next heartbeat, finishes current work, generates artifacts, unregisters. (2) **SIGTERM** — if agent doesn't respond within a few minutes, send SIGTERM. SessionEnd hook generates artifacts and calls unregister (best-effort). (3) **Heartbeat timeout** (F-10) — if all else fails, stale sessions are cleaned up after 3 minutes.
- **SessionEnd hook handles SIGTERM.** If killed externally, the `.claude/hooks/agent-shutdown.sh` hook generates work logs and calls unregister automatically.
- **Artifact handoff is explicit.** The unregister call includes paths to `shutdown-artifacts/work-log.md` and `shutdown-artifacts/learnings.md`. The `WORKTREE_OFFLINE` event carries these paths for the main agent to consolidate.
- **Main agent consolidation.** On receiving `WORKTREE_OFFLINE` with artifacts: read the files, copy work log to `docs/superpowers/work-logs/`, merge learnings into CLAUDE.md, commit, then run `./scripts/manage-worktrees.sh remove {name}`.

### Proof-of-Work Demos
- **Every PR must include a `demo.md` that RUNS what you built, not describes it.** A demo is proof that your code works, not a summary of what you changed.
- **A demo is NOT:** test output, a list of files changed, a description of what was implemented, or grep of source code. Those belong in the PR description, not the demo.
- **A demo IS:** executing the actual feature and showing the output. Think "if I were showing this to a colleague, what would I type in the terminal or click in the browser?"
- **Backend PRs (new endpoints, API changes):** Use Showboat `exec` blocks to curl each new/changed endpoint. Show the request AND the response. Start the backend on your worktree port first.
  ```bash
  # Example: demo for a new message endpoint
  uvx showboat exec demo.md bash 'curl -s -X POST http://localhost:$BACKEND_PORT/api/v1/agents/$WT_ID/message -H "Content-Type: application/json" -H "Authorization: Bearer $API_KEY" -d "{\"message\": \"hello\"}" | jq .'
  ```
- **MCP server PRs (new tools):** You cannot test MCP tools in your own session — your MCP server loaded before your changes. Two demo approaches, use BOTH:
  1. **Curl the backend endpoint** the tool wraps — proves the API works:
     ```bash
     uvx showboat exec demo.md bash 'curl -s -X PATCH http://localhost:$BACKEND_PORT/api/v1/agents/$WT_ID/assign-task -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" -d "{\"task_id\": \"$TASK_ID\"}" | jq .'
     ```
  2. **Launch a fresh Claude session** in a zellij tab to call the actual MCP tool — proves the tool registration and plumbing work end-to-end:
     ```bash
     # Build the MCP server with your changes
     cd mcp-server && npm run build && cd ..
     # Open a zellij tab, run a one-shot claude session that loads the new build
     zellij action new-tab --name "mcp-demo"
     sleep 1
     zellij action write-chars "cd $(pwd) && claude --dangerously-skip-permissions -p 'Use ToolSearch to find mcp__cloglog__assign_task. Load it and call it with worktree_id=X task_id=Y. Report the result.' > /tmp/mcp-demo-result.txt 2>&1"
     sleep 0.5
     zellij action write 13
     # Wait for it to finish, then read the result
     sleep 45
     cat /tmp/mcp-demo-result.txt
     # Clean up
     TAB_ID=$(zellij action list-tabs | awk '$3 == "mcp-demo" {print $1}')
     zellij action close-tab --tab-id "$TAB_ID"
     rm -f /tmp/mcp-demo-result.txt
     ```
     Include the content of `/tmp/mcp-demo-result.txt` in the demo — it's proof the MCP tool works in a real Claude session.
- **Frontend PRs (new UI):** Use Rodney (headless Chrome via `uvx rodney`) to take a screenshot of the new/changed UI. Include before AND after if modifying existing UI.
  ```bash
  uvx rodney screenshot http://localhost:$FRONTEND_PORT --output docs/demos/my-feature/screenshot.png
  uvx showboat image demo.md docs/demos/my-feature/screenshot.png
  ```
- **State machine / guard PRs:** Show both the happy path (allowed transition) AND the rejection (blocked transition with error message).
- `make quality` will fail if a PR is missing its demo.
- Each worktree runs on isolated ports and database. Source `scripts/worktree-ports.sh` in demo scripts.
- Demo scope: feature walkthrough only. Regression testing is handled by E2E tests.

### Infrastructure Isolation
- **Each worktree has its own ports and database.** Created automatically by `create-worktree.sh`.
- Port assignments are in the worktree's `.env` file. Source `scripts/worktree-ports.sh` for env vars.
- Database is named `cloglog_<worktree_name>` (hyphens replaced with underscores).
- **Cleanup is automatic:** `manage-worktrees.sh remove` tears down the database and kills port processes.
- Never hardcode ports. Always use `$BACKEND_PORT`, `$FRONTEND_PORT` from the env.

---

*This section is updated after each wave with learnings from PR reviews. If you encounter a new pattern that future agents should know, note it in your PR description so it can be added here.*

## Tech Stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- MCP Server: Node.js, TypeScript, @modelcontextprotocol/sdk
- Tools: uv, ruff, mypy, pytest
