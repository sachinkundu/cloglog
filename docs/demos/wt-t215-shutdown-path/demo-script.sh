#!/usr/bin/env bash
# Demo: T-215 — request_shutdown writes to <worktree_path>/.cloglog/inbox.
#
# Strategy: run the live end-to-end scenario ONCE against the running backend
# to produce a deterministic artifact (captured-inbox.txt). Every `showboat
# exec` block below only reads from static files in the repo, so
# `uvx showboat verify` re-runs cleanly even when the backend is down
# (required because `make quality` runs demo-check without a server).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"

DEMO_DIR="docs/demos/wt-t215-shutdown-path"
DEMO_FILE="$DEMO_DIR/demo.md"
CAPTURED="$DEMO_DIR/captured-inbox.txt"
BASE="http://localhost:${BACKEND_PORT}/api/v1"

# --- Live scenario: register a worktree, trigger request_shutdown, capture ---
WT_PATH="/tmp/demo-t215-worktree"
rm -rf "$WT_PATH" && mkdir -p "$WT_PATH"

PROJ=$(curl -sf \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -H "Content-Type: application/json" \
  -X POST "$BASE/projects" \
  -d "{\"name\":\"demo-t215-$(date +%s%N)\"}")
API_KEY=$(echo "$PROJ" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")

REG=$(curl -sf \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -X POST "$BASE/agents/register" \
  -d "{\"worktree_path\":\"$WT_PATH\",\"branch_name\":\"wt-demo-t215\"}")
WT_ID=$(echo "$REG" | python3 -c "import sys,json; print(json.load(sys.stdin)['worktree_id'])")

# Trigger the unified path via the real HTTP route that calls
# AgentService.request_shutdown. Gateway requires an auth header on all
# /agents/* routes (checked by app.AuthMiddleware); the dashboard key works.
curl -sf \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -X POST "$BASE/agents/$WT_ID/request-shutdown" >/dev/null

# Freeze the live output into a deterministic file the exec blocks below read.
cp "$WT_PATH/.cloglog/inbox" "$CAPTURED"

# Sanity-check the capture before writing the doc.
python3 -c "
import json, sys
line = open('$CAPTURED').readline()
d = json.loads(line)
assert d['type'] == 'shutdown', f\"unexpected type: {d['type']}\"
print(f'captured one line, type={d[\"type\"]}')
"

# --- Showboat: render proofs that re-verify from the static capture ---
uvx showboat init "$DEMO_FILE" \
  "Cooperative shutdown now reaches worktree agents: request_shutdown writes to <worktree_path>/.cloglog/inbox — the same file every agent already monitors — instead of the dead /tmp/cloglog-inbox-{id} path that blocked T-220 three-tier shutdown."

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — the legacy /tmp/cloglog-inbox- write path is completely removed from src/. Count of matches under src/:"
uvx showboat exec "$DEMO_FILE" bash \
  "grep -rn '/tmp/cloglog-inbox-' src/ | wc -l"

uvx showboat note "$DEMO_FILE" \
  "Proof 2 — request_shutdown now builds the inbox path from worktree.worktree_path. Expected 1 line in src/agent/services.py:"
uvx showboat exec "$DEMO_FILE" bash \
  'grep -cE "Path\(worktree\.worktree_path\) / \"\.cloglog\" / \"inbox\"" src/agent/services.py'

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — docs/design/agent-lifecycle.md's legacy note now reflects the completed migration (phrase 'is removed' present):"
uvx showboat exec "$DEMO_FILE" bash \
  "grep -c 'is removed' docs/design/agent-lifecycle.md"

uvx showboat note "$DEMO_FILE" \
  "Proof 4 — live run. A worktree was registered at /tmp/demo-t215-worktree and POST /agents/{id}/request-shutdown was invoked. The file the backend wrote (<worktree>/.cloglog/inbox) is frozen at docs/demos/wt-t215-shutdown-path/captured-inbox.txt. It contains exactly one line whose JSON type is 'shutdown':"
uvx showboat exec "$DEMO_FILE" bash \
  "wc -l < docs/demos/wt-t215-shutdown-path/captured-inbox.txt"
uvx showboat exec "$DEMO_FILE" bash \
  "python3 -c 'import json; print(json.loads(open(\"docs/demos/wt-t215-shutdown-path/captured-inbox.txt\").readline())[\"type\"])'"

uvx showboat note "$DEMO_FILE" \
  "Proof 5 — full captured JSON body shows the shutdown message the agent will act on:"
uvx showboat exec "$DEMO_FILE" bash \
  "cat docs/demos/wt-t215-shutdown-path/captured-inbox.txt"

uvx showboat verify "$DEMO_FILE"
