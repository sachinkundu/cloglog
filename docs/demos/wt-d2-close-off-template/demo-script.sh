#!/usr/bin/env bash
# Demo for T-246: every worktree creation files a first-class close-off task
# on the board — assigned to the main agent when configured, idempotent on
# re-run, and wired so close-wave PR events route back via Task.pr_url.
#
# Determinism: every captured `exec` block is a static filesystem / code
# inspection or a pre-filtered pytest line. No live HTTP calls, no UUIDs,
# no timestamps — showboat verify re-runs everything deterministically
# without the backend running, which is the state `make demo-check`
# encounters. End-to-end live behavior is exercised by
# tests/agent/test_close_off_task.py (5 integration tests against real
# Postgres via conftest fixtures — their pass count is captured below).
#
# Called by `make demo` (also safe as a standalone showboat verify target
# once the file is committed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"

uvx showboat init "$DEMO_FILE" \
  "Every new worktree auto-files a paired close-off task on the board — assigned to the main agent, idempotent on re-run, and wired so close-wave PR events route back through the standard Task.pr_url primary lookup."

# ---------------------------------------------------------------------------
# 1. Backend route — POST /api/v1/agents/close-off-task
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "The new endpoint lives under /agents/* (same middleware bucket as register_agent and unregister-by-path) so it authenticates with the project API key — exactly what .cloglog/on-worktree-create.sh has available at bootstrap time via ~/.cloglog/credentials. The route is a thin find-or-create wrapper over BoardService.create_close_off_task."

uvx showboat exec "$DEMO_FILE" bash 'grep -n "close-off-task\|create_close_off_task" src/agent/routes.py | head -10'

# ---------------------------------------------------------------------------
# 2. Idempotency column on the task row
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Idempotency is backed by a dedicated column — tasks.close_off_worktree_id — FK to worktrees.id with ON DELETE SET NULL and a UNIQUE constraint. Postgres treats NULLs as distinct for UNIQUE, so at most one live close-off task per worktree exists, and legacy rows whose worktree was deleted keep living on backlog (the spec's 'task lingers as a flag' requirement)."

uvx showboat exec "$DEMO_FILE" bash 'grep -n "close_off_worktree_id" src/board/models.py'

uvx showboat exec "$DEMO_FILE" bash 'grep -n "close_off_worktree_id\|add_column\|create_foreign_key\|create_index" src/alembic/versions/d2a1b3c4e5f6_add_close_off_worktree_id_to_tasks.py | head -8'

# ---------------------------------------------------------------------------
# 3. Template body (stored as a Python constant per the spec's "Option A")
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "The close-off checklist is a Python constant (spec's Option A — no DB-backed template registry until there's a second template). Auto-provisioning the 'Operations' epic and 'Worktree Close-off' feature on first call keeps the caller hands-off."

uvx showboat exec "$DEMO_FILE" bash 'grep -n "CLOSE_OFF_EPIC_TITLE\|CLOSE_OFF_FEATURE_TITLE\|close_worktree_template\|Close-off for worktree" src/board/templates.py | head -10'

# ---------------------------------------------------------------------------
# 4. Service-layer idempotency + main-agent assignment
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "The service's find-or-create path first queries by close_off_worktree_id; on hit, returns the existing task (created=false). On miss, it auto-provisions Ops/Close-off, creates the task, and stamps both worktree_id (main agent, when settings.main_agent_inbox_path is configured) and close_off_worktree_id."

uvx showboat exec "$DEMO_FILE" bash 'grep -n "create_close_off_task\|find_close_off_task\|main_agent_worktree_id\|close_off_worktree_id" src/board/services.py | head -12'

# ---------------------------------------------------------------------------
# 5. MCP tool wrapping the endpoint
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "The MCP tool mcp__cloglog__create_close_off_task wraps the endpoint — same body, same auth (the client routes /agents/close-off-task via the project API key branch, not the agent-token branch). Built into mcp-server/dist/ so live Claude sessions see it immediately after the post-merge sync hook runs."

uvx showboat exec "$DEMO_FILE" bash 'grep -n "create_close_off_task\|close-off-task\|isCloseOffTaskRoute" mcp-server/src/server.ts mcp-server/src/tools.ts mcp-server/src/client.ts | head -12'

uvx showboat exec "$DEMO_FILE" bash '
if [[ -f mcp-server/dist/tools.js ]] && [[ -f mcp-server/dist/server.js ]]; then
  echo "mcp-server/dist/built:             ok"
else
  echo "mcp-server/dist/built:             MISSING"
fi
echo "dist_tool_registered:             $(grep -c create_close_off_task mcp-server/dist/tools.js)"
echo "dist_server_registered:           $(grep -c create_close_off_task mcp-server/dist/server.js)"
'

# ---------------------------------------------------------------------------
# 6. on-worktree-create.sh wiring
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "The worktree-bootstrap hook curls the endpoint with the project API key. It is intentionally non-fatal — if the backend is down or the key is missing, the hook logs and continues rather than wedging worktree creation. The main agent can always re-file the task later via the MCP tool."

uvx showboat exec "$DEMO_FILE" bash 'grep -n "close-off-task\|T-246\|_resolve_api_key\|_resolve_backend_url" .cloglog/on-worktree-create.sh | head -12'

# ---------------------------------------------------------------------------
# 7. Contract compliance — baseline schema runtime check
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "The endpoint ships with its own contract file at docs/contracts/d2-close-off-template.openapi.yaml and is picked up by make contract-check. The contract pins the body (worktree_path + worktree_name) and the response (task_id, task_number, worktree_id, worktree_name, created) so frontend and MCP clients have a single source of truth."

uvx showboat exec "$DEMO_FILE" bash 'grep -nE "close-off-task|CloseOffTaskCreate|CloseOffTaskResponse" docs/contracts/d2-close-off-template.openapi.yaml | head -10'

# ---------------------------------------------------------------------------
# 8. End-to-end integration tests — real Postgres, no mocks
# ---------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" \
  "Five integration tests cover the acceptance criteria: one happy-path (task created + assigned to main), one idempotency (same path → created=false, same id), one 404 (unregistered path), one hierarchy (Ops epic + Close-off feature are reused across worktrees), one webhook routing (AgentNotifierConsumer primary path delivers PR_MERGED into the main inbox via Task.pr_url). All run against a real Postgres database provisioned by conftest.py — no mocks."

uvx showboat exec "$DEMO_FILE" bash '
grep "^async def test" tests/agent/test_close_off_task.py \
  | sed "s/^async def /  - /; s/(.*$//"
'

uvx showboat exec "$DEMO_FILE" bash 'uv run pytest tests/agent/test_close_off_task.py -q 2>&1 | grep -oE "[0-9]+ passed"'

uvx showboat verify "$DEMO_FILE"
