#!/bin/bash
# Demo: Search filters — is:open, is:closed, is:archived qualifiers
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "# Search Filters Demo"
echo ""

# Start backend from worktree — rename .env temporarily to avoid pydantic issues
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

echo "## Setup: project with tasks in backlog, in_progress, done"
echo ""
PROJECT=$(curl -sf -X POST "$API/projects" -H "$CT" -H "$DK" -d '{"name": "search-demo-'$RANDOM'"}')
PID=$(echo "$PROJECT" | jq -r '.id')

EPIC=$(curl -sf -X POST "$API/projects/$PID/epics" -H "$CT" -H "$DK" -d '{"title": "Demo Epic"}')
EID=$(echo "$EPIC" | jq -r '.id')

FEATURE=$(curl -sf -X POST "$API/projects/$PID/epics/$EID/features" -H "$CT" -H "$DK" -d '{"title": "Demo Feature"}')
FID=$(echo "$FEATURE" | jq -r '.id')

curl -sf -X POST "$API/projects/$PID/features/$FID/tasks" -H "$CT" -H "$DK" -d '{"title": "Agent auth backlog task"}' > /dev/null

T2=$(curl -sf -X POST "$API/projects/$PID/features/$FID/tasks" -H "$CT" -H "$DK" -d '{"title": "Agent deploy in progress"}')
T2ID=$(echo "$T2" | jq -r '.id')
curl -sf -X PATCH "$API/tasks/$T2ID" -H "$CT" -H "$DK" -d '{"status": "in_progress"}' > /dev/null

T3=$(curl -sf -X POST "$API/projects/$PID/features/$FID/tasks" -H "$CT" -H "$DK" -d '{"title": "Agent migration done"}')
T3ID=$(echo "$T3" | jq -r '.id')
curl -sf -X PATCH "$API/tasks/$T3ID" -H "$CT" -H "$DK" -d '{"status": "done"}' > /dev/null

echo "Created 3 tasks: backlog, in_progress, done"
echo ""

echo "## 1. Search without filter (returns all 3)"
echo '```json'
curl -sf "$API/projects/$PID/search?q=Agent" -H "$DK" | jq '.results[] | {title, status}'
echo '```'
echo ""

echo "## 2. is:open filter (backlog + in_progress only)"
echo '```json'
curl -sf "$API/projects/$PID/search?q=Agent&status_filter=backlog&status_filter=in_progress&status_filter=review" -H "$DK" | jq '.results[] | {title, status}'
echo '```'
echo ""

echo "## 3. is:closed filter (done only)"
echo '```json'
curl -sf "$API/projects/$PID/search?q=Agent&status_filter=done" -H "$DK" | jq '.results[] | {title, status}'
echo '```'
echo ""

echo "## Frontend qualifier parsing"
echo ""
echo '- `is:open agent` → q=agent&status_filter=backlog&status_filter=in_progress&status_filter=review'
echo '- `is:closed migration` → q=migration&status_filter=done'
echo '- `is:archived old` → q=old&status_filter=archived'
echo ""
echo "Filter pill badge shows next to search input when qualifier is active."
echo ""

echo "## Test Results"
echo ""
echo "### Backend (14 search tests, 4 new)"
echo '```'
cd /home/sachin/code/cloglog
uv run pytest "$SCRIPT_DIR/tests/board/test_routes.py" -v -k search 2>&1 | grep -E "PASSED|FAILED|passed|failed" | tail -20
echo '```'
echo ""

echo "### Frontend (33 tests, 12 new)"
echo '```'
cd "$SCRIPT_DIR/frontend"
npx vitest run src/lib/searchQualifiers.test.ts src/hooks/useSearch.test.ts src/components/SearchWidget.test.tsx 2>&1 | tail -8
echo '```'
