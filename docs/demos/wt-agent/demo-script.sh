#!/bin/bash
# Demo: T-114 Transition Guards
# Exercises all 5 guards via curl against the running backend.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
source "$REPO_ROOT/scripts/worktree-ports.sh"

BASE="http://127.0.0.1:${BACKEND_PORT}/api/v1"

echo "=== T-114: Transition Guards Demo ==="
echo "Backend: $BASE"
echo ""

# --- Setup: create project, register agent, create tasks ---
echo "## Setup: Create project and register agent"
PROJECT=$(curl -s -X POST "$BASE/projects" \
  -H "Content-Type: application/json" \
  -d '{"name": "guard-demo", "description": "Demo project"}')
PROJECT_ID=$(echo "$PROJECT" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
API_KEY=$(echo "$PROJECT" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")
echo "Project: $PROJECT_ID"

REG=$(curl -s -X POST "$BASE/agents/register" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"worktree_path": "/tmp/demo-guard", "branch_name": "wt-demo"}')
WT_ID=$(echo "$REG" | python3 -c "import sys,json; print(json.load(sys.stdin)['worktree_id'])")
echo "Worktree: $WT_ID"

# Create epic, feature, two tasks
EPIC=$(curl -s -X POST "$BASE/epics" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\", \"title\": \"Demo Epic\"}")
EPIC_ID=$(echo "$EPIC" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

FEATURE=$(curl -s -X POST "$BASE/features" \
  -H "Content-Type: application/json" \
  -d "{\"epic_id\": \"$EPIC_ID\", \"title\": \"Demo Feature\"}")
FEATURE_ID=$(echo "$FEATURE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

TASK1=$(curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"feature_id\": \"$FEATURE_ID\", \"title\": \"First task\", \"description\": \"Task 1\"}")
T1_ID=$(echo "$TASK1" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

TASK2=$(curl -s -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d "{\"feature_id\": \"$FEATURE_ID\", \"title\": \"Second task\", \"description\": \"Task 2\"}")
T2_ID=$(echo "$TASK2" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Assign both tasks
curl -s -X PATCH "$BASE/tasks/$T1_ID" \
  -H "Content-Type: application/json" \
  -d "{\"worktree_id\": \"$WT_ID\", \"status\": \"assigned\"}" > /dev/null
curl -s -X PATCH "$BASE/tasks/$T2_ID" \
  -H "Content-Type: application/json" \
  -d "{\"worktree_id\": \"$WT_ID\", \"status\": \"assigned\"}" > /dev/null

echo "Tasks: $T1_ID, $T2_ID"
echo ""

# --- Guard 1: One active task per agent ---
echo "## Guard 1: One active task per agent"
echo "Starting first task..."
curl -s -X POST "$BASE/agents/$WT_ID/start-task" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T1_ID\"}" | python3 -m json.tool
echo ""

echo "Trying to start second task (should fail with 409)..."
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/agents/$WT_ID/start-task" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T2_ID\"}")
echo "HTTP $RESP"
curl -s -X POST "$BASE/agents/$WT_ID/start-task" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T2_ID\"}" | python3 -m json.tool
echo ""

# --- Guard 3: PR URL required for review ---
echo "## Guard 3: PR URL required for review"
echo "Moving to review without PR URL (should fail with 409)..."
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE/agents/$WT_ID/task-status" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T1_ID\", \"status\": \"review\"}")
echo "HTTP $RESP"
curl -s -X PATCH "$BASE/agents/$WT_ID/task-status" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T1_ID\", \"status\": \"review\"}" | python3 -m json.tool
echo ""

echo "Moving to review WITH PR URL (should succeed with 204)..."
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE/agents/$WT_ID/task-status" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T1_ID\", \"status\": \"review\", \"pr_url\": \"https://github.com/demo/repo/pull/1\"}")
echo "HTTP $RESP"
echo ""

# --- Guard 4: Review -> in_progress allowed ---
echo "## Guard 4: Review -> in_progress allowed"
echo "Moving back to in_progress (should succeed with 204)..."
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE/agents/$WT_ID/task-status" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T1_ID\", \"status\": \"in_progress\"}")
echo "HTTP $RESP"
echo ""

# --- Guard 5: Done blocked for agents ---
echo "## Guard 5: Done blocked for agents"
echo "Trying to move to done (should fail with 409)..."
RESP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$BASE/agents/$WT_ID/task-status" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T1_ID\", \"status\": \"done\"}")
echo "HTTP $RESP"
curl -s -X PATCH "$BASE/agents/$WT_ID/task-status" \
  -H "Content-Type: application/json" \
  -d "{\"task_id\": \"$T1_ID\", \"status\": \"done\"}" | python3 -m json.tool
echo ""

# --- Cleanup ---
echo "## Cleanup"
curl -s -X POST "$BASE/agents/$WT_ID/unregister" > /dev/null
echo "Agent unregistered. Demo complete."
