#!/usr/bin/env bash
# Demo: T-164 — search MCP tool wrapping the existing backend search endpoint.
# Called by `make demo`. No running backend required — proofs are local,
# deterministic, and capture reduced summary output (counts, OK/FAIL booleans)
# so `showboat verify` is byte-exact across runs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
DEMO_FILE="$REPO_ROOT/docs/demos/${BRANCH//\//-}/demo.md"

cd "$REPO_ROOT"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Agents can now resolve T-NNN, F-NN, E-N references and free-text queries through mcp__cloglog__search — a thin wrapper over the existing GET /api/v1/projects/{id}/search endpoint, so behaviour matches the CLI's _resolve_task path exactly without paging the full board."

# ---------------------------------------------------------------------------
# Proof 1 — search tool is registered in mcp-server/src/server.ts (source of
# truth; mcp-server/dist/ is a gitignored build artifact).
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — search tool is registered in the source-of-truth server.ts at the same arg position as every other server.tool call."

uvx showboat exec "$DEMO_FILE" bash \
  "SERVER=mcp-server/src/server.ts
   has_search=\$(grep -cE \"^ *'search',\" \"\$SERVER\")
   echo \"search_tool_registered=\$( [[ \$has_search -eq 1 ]] && echo OK || echo FAIL )\""

# ---------------------------------------------------------------------------
# Proof 2 — the handler hits the project-scoped search endpoint with the same
# query-string shape src/gateway/cli.py:189 already uses, so the MCP tool and
# the CLI exercise the exact same backend path.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 2 — handler in src/tools.ts targets /projects/{id}/search and the URL parity with src/gateway/cli.py is pinned (matching shape: ?q=… on the same path)."

uvx showboat exec "$DEMO_FILE" bash \
  'TOOLS=mcp-server/src/tools.ts
   CLI=src/gateway/cli.py
   has_search_path=$(grep -cE "/projects/\\\${project_id}/search" "$TOOLS")
   cli_uses_search=$(grep -cE "/projects/\{project_id\}/search" "$CLI")
   echo "handler_uses_project_search_path=$( [[ $has_search_path -ge 1 ]] && echo OK || echo FAIL )"
   echo "cli_uses_same_endpoint=$( [[ $cli_uses_search -ge 1 ]] && echo OK || echo FAIL )"'

# ---------------------------------------------------------------------------
# Proof 3 — query-string encoding contract. URLSearchParams produces the same
# percent-encoding the FastAPI Query parser already accepts. We pin three
# concrete shapes (entity number, free text with spaces+ampersand, optional
# limit + multi-valued status_filter) so a regression in the wrapper would
# show up as a hash diff on a future run.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — handler URL construction is byte-exact for the three documented call shapes. The vitest cases that pin them (entity number → ?q=T-42, free text → URL-encoded q, limit + multi status_filter → repeated query keys) all pass; output reduced to a count so verify is deterministic."

uvx showboat exec "$DEMO_FILE" bash \
  'cd mcp-server && npx vitest run --reporter=basic src/__tests__/tools.test.ts -t search 2>&1 \
     | grep -oE "Tests  [0-9]+ passed" | head -1'

# ---------------------------------------------------------------------------
# Proof 4 — backend endpoint exists exactly where the wrapper expects it. If
# this drifts (route renamed, method changed) the wrapper is silently broken;
# this pin catches it before make quality runs the contract check.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 4 — backend route the wrapper depends on still lives at GET /api/v1/projects/{project_id}/search."

uvx showboat exec "$DEMO_FILE" bash \
  'ROUTES=src/board/routes.py
   has_route=$(grep -c "/projects/{project_id}/search" "$ROUTES")
   has_get=$(grep -B1 "/projects/{project_id}/search" "$ROUTES" | grep -c "router.get")
   echo "backend_route_present=$( [[ $has_route -ge 1 ]] && echo OK || echo FAIL )"
   echo "backend_route_is_GET=$( [[ $has_get -ge 1 ]] && echo OK || echo FAIL )"'

# ---------------------------------------------------------------------------
# Proof 5 — vitest covers the new tool at both layers (handler URL contract +
# server registration / requireProject guard). Output reduced to "Tests N
# passed" so showboat verify stays deterministic.
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 5 — MCP-server vitest suite passes (handler URL pins + server tool registration + pre-register guard)."

uvx showboat exec "$DEMO_FILE" bash \
  'cd mcp-server && npx vitest run --reporter=basic 2>&1 \
     | grep -oE "Tests  [0-9]+ passed" | head -1'

uvx showboat verify "$DEMO_FILE"
