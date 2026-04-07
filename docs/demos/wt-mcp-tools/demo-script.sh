#!/usr/bin/env bash
# Demo script for T-125: Filtered Board Queries & get_active_tasks
# Called by make demo (run-demo.sh starts the server + DB for us).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"
BASE="http://localhost:${BACKEND_PORT}/api/v1"
H=(-H "X-Dashboard-Key: cloglog-dashboard-dev" -H "Content-Type: application/json")
j() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

echo "--- Setup ---"
PID=$(curl -s "${H[@]}" -X POST "$BASE/projects" -d '{"name":"demo-t125"}' | j "['id']")
E1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics" -d '{"title":"Auth"}' | j "['id']")
E2=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics" -d '{"title":"Board"}' | j "['id']")
F1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics/$E1/features" -d '{"title":"Login"}' | j "['id']")
F2=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics/$E2/features" -d '{"title":"Kanban"}' | j "['id']")

T1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/features/$F1/tasks" -d '{"title":"T1-backlog"}' | j "['id']")
T2=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/features/$F1/tasks" -d '{"title":"T2-progress"}' | j "['id']")
curl -s "${H[@]}" -X PATCH "$BASE/tasks/$T2" -d '{"status":"in_progress"}' >/dev/null
T3=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/features/$F1/tasks" -d '{"title":"T3-done"}' | j "['id']")
curl -s "${H[@]}" -X PATCH "$BASE/tasks/$T3" -d '{"status":"done"}' >/dev/null
T4=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/features/$F2/tasks" -d '{"title":"T4-review"}' | j "['id']")
curl -s "${H[@]}" -X PATCH "$BASE/tasks/$T4" -d '{"status":"review"}' >/dev/null
echo "Created project with 4 tasks: backlog, in_progress, done, review"

echo ""
echo "--- 1. Board (no filters - backward compat) ---"
curl -s "${H[@]}" "$BASE/projects/$PID/board" | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(f'total_tasks={d[\"total_tasks\"]}, done_count={d[\"done_count\"]}')
assert d['total_tasks'] == 4, 'Expected 4 tasks'
print('PASS: All 4 tasks returned')
"

echo ""
echo "--- 2. Board with exclude_done=true ---"
curl -s "${H[@]}" "$BASE/projects/$PID/board?exclude_done=true" | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(f'total_tasks={d[\"total_tasks\"]}, done_count={d[\"done_count\"]}')
assert d['total_tasks'] == 3, 'Expected 3 tasks'
assert d['done_count'] == 0, 'Expected 0 done'
print('PASS: Done tasks excluded')
"

echo ""
echo "--- 3. Board filtered by status ---"
curl -s "${H[@]}" "$BASE/projects/$PID/board?status=in_progress&status=review" | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(f'total_tasks={d[\"total_tasks\"]}')
assert d['total_tasks'] == 2, 'Expected 2 tasks'
print('PASS: Only in_progress + review tasks')
"

echo ""
echo "--- 4. Board filtered by epic ---"
curl -s "${H[@]}" "$BASE/projects/$PID/board?epic_id=$E1" | python3 -c "
import sys, json; d=json.load(sys.stdin)
print(f'total_tasks={d[\"total_tasks\"]}')
assert d['total_tasks'] == 3, 'Expected 3 tasks under Auth epic'
print('PASS: Only Auth epic tasks')
"

echo ""
echo "--- 5. Active tasks endpoint ---"
curl -s "${H[@]}" "$BASE/projects/$PID/active-tasks" | python3 -c "
import sys, json
tasks=json.load(sys.stdin)
print(f'active_count={len(tasks)}')
for t in tasks: print(f'  {t[\"title\"]} [{t[\"status\"]}]')
size=len(json.dumps(tasks))
print(f'Response size: {size} chars')
assert len(tasks) == 3, 'Expected 3 active tasks'
# Verify compact schema
assert 'description' not in tasks[0], 'Should not include description'
assert 'created_at' not in tasks[0], 'Should not include created_at'
assert 'task_type' in tasks[0], 'Should include task_type'
print('PASS: Compact active tasks returned')
"

echo ""
echo "=== All assertions passed ==="
