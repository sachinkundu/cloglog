#!/bin/bash
# Demo: Project description validation — reject empty strings with 422
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "# Project Description Validation Demo"
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

echo "## 1. Reject empty description (should return 422)"
echo '```'
HTTP_CODE=$(curl -s -o /tmp/demo-empty-desc.json -w "%{http_code}" -X POST "$API/projects" -H "$CT" -H "$DK" -d '{"name": "test-project", "description": ""}')
echo "HTTP $HTTP_CODE"
jq . /tmp/demo-empty-desc.json
echo '```'
echo ""

echo "## 2. Accept valid description (should return 201)"
echo '```'
HTTP_CODE=$(curl -s -o /tmp/demo-valid-desc.json -w "%{http_code}" -X POST "$API/projects" -H "$CT" -H "$DK" -d '{"name": "test-project-valid", "description": "A real project"}')
echo "HTTP $HTTP_CODE"
jq '{id: .id, name: .name, description: .description}' /tmp/demo-valid-desc.json
echo '```'
echo ""

echo "## 3. Omit description (should use default, return 201)"
echo '```'
HTTP_CODE=$(curl -s -o /tmp/demo-no-desc.json -w "%{http_code}" -X POST "$API/projects" -H "$CT" -H "$DK" -d '{"name": "test-project-default"}')
echo "HTTP $HTTP_CODE"
jq '{id: .id, name: .name, description: .description}' /tmp/demo-no-desc.json
echo '```'
echo ""

# Cleanup temp files
rm -f /tmp/demo-empty-desc.json /tmp/demo-valid-desc.json /tmp/demo-no-desc.json
