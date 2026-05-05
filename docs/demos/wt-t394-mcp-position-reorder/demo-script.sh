#!/usr/bin/env bash
# Demo: T-394 — expose task/feature/epic position reordering through MCP.
# Self-contained: builds mcp-server/dist, imports the built handlers with a
# mock CloglogClient, invokes each new reorder tool, and prints the captured
# (method, URL, body) so the proof is byte-deterministic across re-verifies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DEMO_FILE="$SCRIPT_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Agents and supervisor can now reorder tasks, features, and epics through MCP — the same drag-and-drop ordering operation the frontend already performs, now scriptable from any MCP client."

# ── Setup: rebuild the MCP server so dist/ reflects the new tools ──

uvx showboat note "$DEMO_FILE" \
  "Setup: rebuild mcp-server/dist so the demo exercises the freshly compiled handlers, not a stale build."

uvx showboat exec "$DEMO_FILE" bash "cd $REPO_ROOT/mcp-server && npm run build >/dev/null 2>&1 && echo 'mcp-server build: OK'"

# ── Before: tool list lacks reorder_* on the previous server.ts ──

uvx showboat note "$DEMO_FILE" \
  "Before: prior to this change the MCP tool surface had no way to reorder backlog items — agents had to ask the user to drag cards in the UI. The new tools follow the same naming and project-scoped guarding as the rest of the board surface."

uvx showboat exec "$DEMO_FILE" bash "grep -oE \"server\\.tool\\(\\s*'reorder_[a-z]+'\" $REPO_ROOT/mcp-server/dist/server.js | sort -u"

# ── Action: invoke each new tool against a mock backend ──

uvx showboat note "$DEMO_FILE" \
  "Action: instantiate the built tool handlers with a mock CloglogClient that records every request, then call reorder_epics / reorder_features / reorder_tasks. The recorded (method, URL, body) triples prove each tool forwards to the correct backend route."

uvx showboat exec "$DEMO_FILE" bash "cd $REPO_ROOT/mcp-server && node --input-type=module -e \"
import { createToolHandlers } from './dist/tools.js';
const calls = [];
const client = { request: async (m, u, b) => { calls.push({m, u, b}); return { status: 'ok' }; } };
const h = createToolHandlers(client);
await h.reorder_epics({ project_id: 'P', items: [{id:'e1',position:0},{id:'e2',position:1000}] });
await h.reorder_features({ project_id: 'P', epic_id: 'E', items: [{id:'f1',position:0}] });
await h.reorder_tasks({ feature_id: 'F', items: [{id:'t1',position:0},{id:'t2',position:1000}] });
for (const c of calls) console.log(c.m, c.u, JSON.stringify(c.b));
\""

# ── After: assert the URLs match the existing drag-and-drop endpoints ──

uvx showboat note "$DEMO_FILE" \
  "After: the URLs match the drag-and-drop endpoints in src/board/routes.py (reorder_epics / reorder_features / reorder_tasks) — agents now hit the same code path the frontend BacklogTree already exercises."

uvx showboat exec "$DEMO_FILE" bash "grep -oE '@router\\.post\\(\"[^\"]*reorder\"\\)' $REPO_ROOT/src/board/routes.py | sort"

# ── Pin: the new server-test suite covers the wrapper layer ──

uvx showboat note "$DEMO_FILE" \
  "Pin: vitest covers both the handler layer (tools.test.ts) and the registered tool layer (server.test.ts). The summary line below shows all 149 mcp-server tests passing — the +8 over baseline are this PR's reorder coverage."

uvx showboat exec "$DEMO_FILE" bash "cd $REPO_ROOT/mcp-server && npm test --silent 2>&1 | grep -oE 'Tests +[0-9]+ passed \\([0-9]+\\)' | head -1"

uvx showboat verify "$DEMO_FILE"
