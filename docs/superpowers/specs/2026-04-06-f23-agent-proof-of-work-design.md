# F-23: Agent Proof-of-Work Demo Documents — Design Spec

## Problem

Agents produce PRs with unit/integration test reports, but there's no proof the feature actually works end-to-end. Backend tests pass but nobody verifies the API behaves correctly with real requests. Frontend tests pass in jsdom while the rendered app may be broken. Reviewers have no way to verify correctness without manually running the app and exercising the endpoints.

## Solution

After completing work, agents use **Showboat** (executable document builder) to produce a reproducible `demo.md` that proves the feature works. For frontend changes, agents additionally use **Rodney** (headless Chrome CLI) to capture screenshots. The demo is committed to the PR branch and summarized in the PR description.

**Key principle:** Showboat works independently of Rodney. Every PR — backend or frontend — produces a `demo.md`. Rodney is only used when there are actual UI changes to screenshot.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| When to produce demo | Post-implementation, before PR | Keeps implementation loop fast; demo is a verification step |
| What to demo | Feature walkthrough only | Regression testing is handled by E2E suite (F-22) |
| Which PRs need demos | ALL PRs (backend and frontend) | Backend work is proven via curl/API calls in Showboat; frontend adds Rodney screenshots |
| Showboat vs Rodney | Showboat always, Rodney only for UI | Showboat is the core tool — it captures shell command output. Rodney is an add-on for browser screenshots |
| How to deliver | Committed to branch + PR comment | Committed = reproducible via `showboat verify`; PR comment = easy review; both = historical record |
| Demo filename | `demo.md` (canonical) | Consistent naming across all features |
| Enforcement | `make demo` target + `make quality` check | Scriptable, testable, works for any developer, integrated into existing gate |
| Infrastructure isolation | Per-worktree ports + databases | Worktrees run concurrently; port conflicts and shared DBs cause flaky demos |

## Architecture

### Tools

- **Rodney** (`uvx rodney`): Headless Chrome automation via CLI. Start browser, navigate, click, type, screenshot, assert — all shell commands.
- **Showboat** (`uvx showboat`): Builds executable markdown documents from sequential CLI commands. Supports `verify` to re-run and diff all outputs.

Both are installed on-demand via `uvx` (no permanent dependency). Agents access them through shell commands.

### Demo Workflow — Backend PRs

```
Agent completes implementation
        │
        ▼
   make demo
        │
        ├── 1. Start isolated infrastructure (worktree-specific ports + DB)
        ├── 2. Start backend server on worktree-assigned port
        ├── 3. Wait for health check
        ├── 4. showboat init docs/demos/<feature>/demo.md "<Feature Title>"
        │
        ├── 5. For each key endpoint/behavior:
        │      ├── showboat exec <file> "curl -s http://localhost:<port>/api/..."
        │      ├── showboat note <file> "<explanation of what this proves>"
        │      └── (Showboat captures command output inline in the doc)
        │
        ├── 6. showboat verify docs/demos/<feature>/demo.md
        ├── 7. Stop servers and tear down infrastructure
        │
        └── 8. Commit demo doc
```

### Demo Workflow — Frontend PRs

```
Agent completes implementation
        │
        ▼
   make demo
        │
        ├── 1. Start isolated infrastructure (worktree-specific ports + DB)
        ├── 2. Start backend on worktree-assigned port
        ├── 3. Start frontend on worktree-assigned port
        ├── 4. Wait for servers to be ready
        ├── 5. rodney start (headless Chrome)
        ├── 6. showboat init docs/demos/<feature>/demo.md "<Feature Title>"
        │
        ├── 7. For each key state of the feature:
        │      ├── rodney open http://localhost:<frontend-port>/...
        │      ├── rodney wait / rodney waitstable
        │      ├── rodney screenshot <file>.png
        │      ├── showboat note <file> "<explanation>"
        │      ├── showboat image <file> '![description](<screenshot>.png)'
        │      └── rodney assert / rodney text / rodney exists (verification)
        │
        ├── 8. showboat verify docs/demos/<feature>/demo.md
        ├── 9. rodney stop
        ├── 10. Stop servers and tear down infrastructure
        │
        └── 11. Commit demo doc + screenshots
```

### Directory Structure

```
docs/demos/
├── f22-e2e-test-suite/
│   ├── demo.md            ← Showboat document (canonical name)
│   ├── 001-board-view.png ← Screenshots (frontend PRs only)
│   ├── 002-task-detail.png
│   └── ...
├── f23-proof-of-work/
│   ├── demo.md
│   └── ...
├── f10-heartbeat-timeout/
│   └── demo.md            ← Backend-only: no screenshots, just curl output
```

Each feature gets its own subdirectory under `docs/demos/`. The Showboat document is always `demo.md`. Screenshots are stored alongside it for frontend PRs.

### Isolated Infrastructure Per Worktree

Each worktree runs its own infrastructure to avoid port conflicts and shared state between concurrent agents.

#### Port Allocation

Each worktree gets a deterministic port range derived from its name:

```bash
# scripts/worktree-ports.sh — sources into worktree env
# Hash the worktree name to a base port in the range 10000-60000
WORKTREE_NAME=$(basename "$WORKTREE_PATH")
BASE_PORT=$(( ($(echo "$WORKTREE_NAME" | cksum | cut -d' ' -f1) % 50000) + 10000 ))

export BACKEND_PORT=$BASE_PORT
export FRONTEND_PORT=$((BASE_PORT + 1))
export DB_PORT=$((BASE_PORT + 2))
```

The `create-worktree.sh` script sources this and writes the ports into the worktree's `.env` file.

#### Database Isolation

Each worktree gets its own PostgreSQL database within the shared PostgreSQL instance:

```bash
# Database name derived from worktree name
DB_NAME="cloglog_${WORKTREE_NAME//-/_}"

# Create the database if it doesn't exist
psql -h 127.0.0.1 -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
  || psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE $DB_NAME"

# Run migrations against the worktree database
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/$DB_NAME" alembic upgrade head
```

#### Infrastructure Cleanup

When a worktree is removed (via `manage-worktrees.sh remove`), its infrastructure is torn down:

1. **Stop any running servers** bound to the worktree's ports
2. **Drop the worktree database**: `psql -h 127.0.0.1 -U postgres -c "DROP DATABASE IF EXISTS $DB_NAME"`
3. **Remove Docker containers** tagged with the worktree name (if any)
4. **Remove the .env file** containing port assignments

This is added as a cleanup hook in `manage-worktrees.sh` so it runs automatically — agents don't need to remember to clean up.

#### Why Not Docker Compose Per Worktree?

Simpler: separate databases in the existing PostgreSQL instance avoids spinning up N Docker Compose stacks. The backend and frontend are already run as processes (not containers), so only the database needs isolation. If a worktree needs additional services (Redis, etc.), those can be added to the worktree's Docker Compose override file with worktree-specific port mappings.

### `make demo` Target

A new Makefile target that orchestrates the full demo workflow:

```makefile
demo:
	@echo "Running proof-of-work demo..."
	@scripts/run-demo.sh
```

The `scripts/run-demo.sh` script:

1. **Detects which feature is being demoed** — reads from a `DEMO_FEATURE` env var or the current branch name
2. **Sources worktree ports** — loads `scripts/worktree-ports.sh` to get isolated port assignments
3. **Creates worktree database** if it doesn't exist, runs migrations
4. **Starts servers** — backend (and frontend if needed) on worktree-specific ports, waits for health checks
5. **Runs the demo script** — executes `docs/demos/<feature>/demo-script.sh` if it exists (agent-authored), otherwise runs a default smoke test
6. **Cleans up** — stops servers, stops Rodney (if started). Does NOT drop the database (that happens on worktree removal)

### Demo Script (Agent-Authored)

Each feature's demo is driven by a shell script that the agent writes as part of its implementation:

**Backend demo script example** (Showboat only — no Rodney):

```bash
#!/bin/bash
# docs/demos/f10-heartbeat-timeout/demo-script.sh
# Proves the heartbeat timeout cleanup works via API calls

source scripts/worktree-ports.sh
DEMO_FILE="docs/demos/f10-heartbeat-timeout/demo.md"
API="http://localhost:${BACKEND_PORT}/api"

showboat init "$DEMO_FILE" "F-10: Heartbeat Timeout Cleanup"

showboat note "$DEMO_FILE" "Register an agent and verify it appears."
showboat exec "$DEMO_FILE" "curl -s $API/agents | jq '.agents | length'"

showboat note "$DEMO_FILE" "Simulate stale heartbeat and verify cleanup runs."
showboat exec "$DEMO_FILE" "curl -s -X POST $API/agents/cleanup | jq ."

showboat verify "$DEMO_FILE"
```

**Frontend demo script example** (Showboat + Rodney):

```bash
#!/bin/bash
# docs/demos/f20-drag-and-drop/demo-script.sh
# Proves drag-and-drop backlog prioritization works

source scripts/worktree-ports.sh
DEMO_FILE="docs/demos/f20-drag-and-drop/demo.md"

showboat init "$DEMO_FILE" "F-20: Drag-and-Drop Backlog Prioritization"

showboat note "$DEMO_FILE" "Load the board and verify tasks are displayed."
rodney open http://localhost:${FRONTEND_PORT}/projects
rodney waitstable
rodney screenshot docs/demos/f20-drag-and-drop/001-board-view.png
showboat image "$DEMO_FILE" '![Board with tasks](001-board-view.png)'

showboat note "$DEMO_FILE" "Drag a task from backlog to in-progress."
# rodney drag/click commands...
rodney waitstable
rodney screenshot docs/demos/f20-drag-and-drop/002-after-drag.png
showboat image "$DEMO_FILE" '![Task moved](002-after-drag.png)'

showboat verify "$DEMO_FILE"
```

### Quality Gate Integration

The `make quality` target is extended to check for demo documents on ALL PRs:

```makefile
quality: lint typecheck test coverage contract-check demo-check

demo-check:
	@scripts/check-demo.sh
```

`scripts/check-demo.sh`:
- Detects the current feature from branch name or `DEMO_FEATURE` env var
- Checks that `docs/demos/<feature>/demo.md` exists
- Verifies `showboat verify` passes (outputs still match)
- Exits non-zero with a clear message if demo is missing or verification fails

This means:
- **All PRs**: demo required, enforced by quality gate
- Backend PRs: `demo.md` with curl/API output via Showboat
- Frontend PRs: `demo.md` with screenshots via Showboat + Rodney
- The existing pre-commit hook (`quality-gate-before-commit.sh`) already runs `make quality`, so this is automatically enforced

### PR Integration

After the demo is committed, the agent includes it in the PR:

**PR body for backend PRs:**
```markdown
## Demo

A proof-of-work demo document is at [`docs/demos/<feature>/demo.md`](link).

To re-verify: `showboat verify docs/demos/<feature>/demo.md`
```

**PR body for frontend PRs (adds screenshots):**
```markdown
## Demo

A proof-of-work demo document is at [`docs/demos/<feature>/demo.md`](link).

To re-verify: `showboat verify docs/demos/<feature>/demo.md`

### Screenshots

![Board view](docs/demos/<feature>/001-board-view.png)
![Feature detail](docs/demos/<feature>/002-feature-detail.png)
```

Screenshots are embedded directly in the PR body so reviewers see them without navigating to files.

### CLAUDE.md Updates

Add to Agent Learnings section:

```markdown
### Proof-of-Work Demos
- **Every PR must include a `demo.md`.** After implementation, run `make demo` to produce it.
- Backend PRs: use Showboat with curl commands to prove APIs work. No Rodney needed.
- Frontend PRs: use Showboat + Rodney (headless Chrome) for screenshots. Both available via `uvx`.
- Write a `demo-script.sh` in your feature's `docs/demos/<feature>/` directory.
- The demo script should exercise affected endpoints/pages and capture proof of correctness.
- Demo documents are committed to the branch and summarized in the PR description.
- `make quality` will fail if a PR is missing its demo.
- Demo scope: feature walkthrough only. Regression testing is handled by E2E tests.
- Each worktree runs on isolated ports and database. Source `scripts/worktree-ports.sh` in demo scripts.
```

## Agent Workflow Integration

### For All Worktree Agents

The agent's implementation phase gains a new final step:

1. Write code
2. Write tests
3. Run tests
4. **Write demo-script.sh** (using curl for backend, Rodney for frontend)
5. **Run `make demo`**
6. Commit everything (code + tests + demo)
7. Push and create PR (with demo summary in PR body; screenshots for frontend PRs)

### For the `create-worktree.sh` Script

All worktree CLAUDE.md templates should include demo instructions and infrastructure setup. Add after the testing section:

```
## Demo

After implementation, write a demo script and run `make demo`.
See the Proof-of-Work Demos section in the root CLAUDE.md for details.

## Infrastructure

This worktree uses isolated infrastructure. Ports and DB are in `.env`.
Source `scripts/worktree-ports.sh` for port assignments.
```

The script also:
- Sources `scripts/worktree-ports.sh` to generate port assignments
- Creates the worktree database
- Writes a `.env` file with `BACKEND_PORT`, `FRONTEND_PORT`, `DB_PORT`, `DATABASE_URL`

## Dependencies

- **Showboat**: `uvx showboat` (Go binary, distributed via PyPI) — required for all demos
- **Rodney**: `uvx rodney` (Go binary, distributed via PyPI) — required only for frontend demos
- Both are ephemeral (`uvx` downloads on first use, cached afterward)
- No changes to `pyproject.toml` or `package.json`
- Requires Chrome/Chromium installed on the agent VM (already available) — only for frontend demos

## Edge Cases

- **No Chrome available**: `rodney start` fails with a clear error. Backend demos still work (no Rodney needed). Frontend demos should note Chrome absence in PR.
- **Server startup failure**: `run-demo.sh` health-checks servers with timeout. Fails clearly if they don't start.
- **Port collision**: The hash-based port allocation makes collisions unlikely. If detected (port already in use), `run-demo.sh` should retry with an offset and update `.env`.
- **Flaky screenshots**: Rodney's `waitstable` command waits for DOM to stop changing. Use it before every screenshot.
- **Large screenshots**: PNG files can be large. Use `rodney screenshot -w 1280 -h 720` for consistent viewport size and reasonable file sizes.
- **Demo verification drift**: If code changes after demo, `showboat verify` will catch it. Agent should re-run `make demo` before final push.
- **Database cleanup failure**: If `manage-worktrees.sh remove` fails to drop the DB, it logs a warning but continues. A periodic cleanup script can catch orphaned databases.
- **Stale containers**: `manage-worktrees.sh remove` kills any processes bound to the worktree's ports and removes tagged containers.

## What This Does NOT Cover

- **Visual regression testing** (F-24) — screenshot diffing across PRs
- **E2E regression tests** (F-22) — Playwright test suite for all routes
- **Accessibility audits** (F-25) — a11y checks via Rodney or Playwright

## Success Criteria

1. **All PRs** include a `docs/demos/<feature>/demo.md` proving the feature works
2. Backend PRs: `demo.md` contains curl command outputs captured by Showboat
3. Frontend PRs: `demo.md` additionally contains screenshots captured by Rodney
4. `showboat verify` can re-run the demo and confirm outputs match
5. `make quality` fails if any PR is missing its demo
6. Each worktree runs on isolated ports and database — no interference between concurrent agents
7. Worktree removal cleans up database and stops any associated infrastructure
8. Agents can produce demos autonomously with no human intervention
