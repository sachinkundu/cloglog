#!/bin/bash
# Demo: T-135 — Agent Messaging Tests & Cleanup
# Exercises the agent messaging endpoint with curl to prove the API works.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

export WORKTREE_PATH="$REPO_ROOT"
source "$REPO_ROOT/scripts/worktree-ports.sh"

API="http://127.0.0.1:${BACKEND_PORT}/api/v1"

echo "=== T-135 Demo: Agent Messaging ==="
echo ""

# 1. Create a project
echo "--- Creating project ---"
PROJECT=$(curl -s -X POST "$API/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "demo-messaging", "description": "T-135 demo"}')
echo "$PROJECT" | python3 -m json.tool
PROJECT_ID=$(echo "$PROJECT" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")
API_KEY=$(echo "$PROJECT" | python3 -c "import sys, json; print(json.load(sys.stdin)['api_key'])")
AUTH="Authorization: Bearer $API_KEY"

# 2. Register an agent
echo ""
echo "--- Registering agent ---"
REG=$(curl -s -X POST "$API/agents/register" \
  -H "Content-Type: application/json" \
  -H "$AUTH" \
  -d '{"worktree_path": "/tmp/demo-wt", "branch_name": "wt-demo"}')
echo "$REG" | python3 -m json.tool
WT_ID=$(echo "$REG" | python3 -c "import sys, json; print(json.load(sys.stdin)['worktree_id'])")

# 3. Send a message to the agent
echo ""
echo "--- Sending message to agent ---"
MSG_RESP=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "$API/agents/$WT_ID/message" \
  -H "Content-Type: application/json" \
  -d '{"message": "Please rebase on main before merging", "sender": "main-agent"}')
echo "$MSG_RESP"

# 4. Heartbeat picks up the message
echo ""
echo "--- Heartbeat (should contain pending_messages) ---"
HB=$(curl -s -X POST "$API/agents/$WT_ID/heartbeat")
echo "$HB" | python3 -m json.tool

# 5. Second heartbeat — messages should be drained
echo ""
echo "--- Second heartbeat (messages should be drained) ---"
HB2=$(curl -s -X POST "$API/agents/$WT_ID/heartbeat")
echo "$HB2" | python3 -m json.tool

# 6. Message to unknown agent → 404
echo ""
echo "--- Message to unknown agent (expect 404) ---"
UNKNOWN=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST \
  "$API/agents/00000000-0000-0000-0000-000000000000/message" \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "sender": "system"}')
echo "$UNKNOWN"

echo ""
echo "=== Demo complete ==="
