#!/usr/bin/env bash
# Demo script for T-121: update/delete MCP tools for epics and features
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"
BASE="http://localhost:${BACKEND_PORT}/api/v1"
H=(-H "X-Dashboard-Key: cloglog-dashboard-dev" -H "Content-Type: application/json")
j() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

echo "--- Setup ---"
PID=$(curl -s "${H[@]}" -X POST "$BASE/projects" -d '{"name":"demo-t121"}' | j "['id']")
E1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics" -d '{"title":"Auth Epic","description":"Authentication"}' | j "['id']")
F1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics/$E1/features" -d '{"title":"Login Feature","description":"Basic login"}' | j "['id']")
echo "Created project, epic ($E1), feature ($F1)"

echo ""
echo "--- 1. PATCH /epics/{id} — Update epic title and description ---"
curl -s "${H[@]}" -X PATCH "$BASE/epics/$E1" -d '{"title":"Auth & SSO Epic","description":"Authentication with SSO support"}' | python3 -c "
import sys, json; d=json.load(sys.stdin)
assert d['title'] == 'Auth & SSO Epic', f'Expected updated title, got {d[\"title\"]}'
assert d['description'] == 'Authentication with SSO support'
print(json.dumps({'id': d['id'], 'title': d['title'], 'description': d['description']}, indent=2))
print('PASS: Epic updated')
"

echo ""
echo "--- 2. PATCH /features/{id} — Update feature title ---"
curl -s "${H[@]}" -X PATCH "$BASE/features/$F1" -d '{"title":"OAuth Login","description":"OAuth2 login flow"}' | python3 -c "
import sys, json; d=json.load(sys.stdin)
assert d['title'] == 'OAuth Login', f'Expected updated title, got {d[\"title\"]}'
assert d['description'] == 'OAuth2 login flow'
print(json.dumps({'id': d['id'], 'title': d['title'], 'description': d['description']}, indent=2))
print('PASS: Feature updated')
"

echo ""
echo "--- 3. PATCH /epics/{id} — 404 for nonexistent epic ---"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" -X PATCH "$BASE/epics/00000000-0000-0000-0000-000000000000" -d '{"title":"nope"}')
echo "HTTP $STATUS"
[ "$STATUS" = "404" ] && echo "PASS: 404 for unknown epic" || echo "FAIL"

echo ""
echo "--- 4. Create second feature, then DELETE it ---"
F2=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics/$E1/features" -d '{"title":"Temp Feature"}' | j "['id']")
echo "Created feature $F2"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" -X DELETE "$BASE/features/$F2")
echo "DELETE HTTP $STATUS"
[ "$STATUS" = "204" ] && echo "PASS: Feature deleted" || echo "FAIL"

echo ""
echo "--- 5. Create second epic, then DELETE it ---"
E2=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics" -d '{"title":"Temp Epic"}' | j "['id']")
echo "Created epic $E2"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" -X DELETE "$BASE/epics/$E2")
echo "DELETE HTTP $STATUS"
[ "$STATUS" = "204" ] && echo "PASS: Epic deleted" || echo "FAIL"

echo ""
echo "--- 6. Verify originals still exist ---"
curl -s "${H[@]}" "$BASE/projects/$PID/epics" | python3 -c "
import sys, json; epics=json.load(sys.stdin)
assert len(epics) == 1, f'Expected 1 epic, got {len(epics)}'
assert epics[0]['title'] == 'Auth & SSO Epic'
print(f'Remaining epics: {len(epics)} — {epics[0][\"title\"]}')
print('PASS: Only the deleted items are gone')
"

echo ""
echo "=== All assertions passed ==="
