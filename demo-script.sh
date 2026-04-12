#!/bin/bash
# Demo: GET /projects/{id}/stats endpoint
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "# Project Stats Endpoint Demo"
echo ""

# Start backend from worktree
cd "$SCRIPT_DIR"
mv .env .env.bak 2>/dev/null || true
uv run uvicorn src.gateway.app:create_app --factory --port 18999 --host 127.0.0.1 > /dev/null 2>&1 &
BACKEND_PID=$!
cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
  cd "$SCRIPT_DIR"
  mv .env.bak .env 2>/dev/null || true
}
trap cleanup EXIT
sleep 4

API="http://127.0.0.1:18999/api/v1"
DK="X-Dashboard-Key: cloglog-dashboard-dev"
CT="Content-Type: application/json"

echo "## Setup: project with tasks in various statuses"
echo ""
PROJECT=$(curl -sf -X POST "$API/projects" -H "$CT" -H "$DK" -d '{"name": "stats-demo-'$RANDOM'"}')
PID=$(echo "$PROJECT" | jq -r '.id')

EPIC=$(curl -sf -X POST "$API/projects/$PID/epics" -H "$CT" -H "$DK" -d '{"title": "Stats Epic"}')
EID=$(echo "$EPIC" | jq -r '.id')

F1=$(curl -sf -X POST "$API/projects/$PID/epics/$EID/features" -H "$CT" -H "$DK" -d '{"title": "Feature Alpha"}')
F1ID=$(echo "$F1" | jq -r '.id')

F2=$(curl -sf -X POST "$API/projects/$PID/epics/$EID/features" -H "$CT" -H "$DK" -d '{"title": "Feature Beta"}')
F2ID=$(echo "$F2" | jq -r '.id')

# Create tasks in different statuses
curl -sf -X POST "$API/projects/$PID/features/$F1ID/tasks" -H "$CT" -H "$DK" -d '{"title": "Backlog task 1"}' > /dev/null
curl -sf -X POST "$API/projects/$PID/features/$F1ID/tasks" -H "$CT" -H "$DK" -d '{"title": "Backlog task 2"}' > /dev/null

T3=$(curl -sf -X POST "$API/projects/$PID/features/$F1ID/tasks" -H "$CT" -H "$DK" -d '{"title": "In-progress task"}')
T3ID=$(echo "$T3" | jq -r '.id')
curl -sf -X PATCH "$API/tasks/$T3ID" -H "$CT" -H "$DK" -d '{"status": "in_progress"}' > /dev/null

T4=$(curl -sf -X POST "$API/projects/$PID/features/$F2ID/tasks" -H "$CT" -H "$DK" -d '{"title": "Done task 1"}')
T4ID=$(echo "$T4" | jq -r '.id')
curl -sf -X PATCH "$API/tasks/$T4ID" -H "$CT" -H "$DK" -d '{"status": "done"}' > /dev/null

T5=$(curl -sf -X POST "$API/projects/$PID/features/$F2ID/tasks" -H "$CT" -H "$DK" -d '{"title": "Review task"}')
T5ID=$(echo "$T5" | jq -r '.id')
curl -sf -X PATCH "$API/tasks/$T5ID" -H "$CT" -H "$DK" -d '{"status": "review"}' > /dev/null

echo "Created 5 tasks: 2 backlog, 1 in_progress, 1 review, 1 done"
echo "Created 2 features (Feature Beta has all tasks done -> should count as done)"
echo ""

echo "## 1. GET /projects/{id}/stats"
echo '```json'
curl -sf "$API/projects/$PID/stats" -H "$DK" | jq .
echo '```'
echo ""

echo "## 2. Stats for nonexistent project (404)"
echo '```json'
curl -s -w "\nHTTP %{http_code}\n" "$API/projects/00000000-0000-0000-0000-000000000000/stats" -H "$DK" | head -3
echo '```'
echo ""

echo "## 3. Mark Feature Beta as done and check updated completion"
echo ""
curl -sf -X PATCH "$API/features/$F2ID" -H "$CT" -H "$DK" -d '{"status": "done"}' > /dev/null
echo "Marked Feature Beta as done."
echo '```json'
curl -sf "$API/projects/$PID/stats" -H "$DK" | jq '{feature_completion_percentage, task_counts: {total: .task_counts.total, done: .task_counts.done}}'
echo '```'
echo ""

echo "## Test Results"
echo '```'
cd /home/sachin/code/cloglog
uv run pytest "$SCRIPT_DIR/tests/board/test_routes.py" -v -k stats 2>&1 | grep -E "PASSED|FAILED|passed|failed" | tail -20
echo '```'
