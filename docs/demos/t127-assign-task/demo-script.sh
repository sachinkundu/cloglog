#!/usr/bin/env bash
# Demo script for T-127: assign_task MCP tool
# Proves: assign a task to a worktree, verify it shows up in get_my_tasks,
# and confirm the notification message is delivered via heartbeat.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"
BASE="http://localhost:${BACKEND_PORT}/api/v1"
H=(-H "X-Dashboard-Key: cloglog-dashboard-dev" -H "Content-Type: application/json")
j() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

echo "--- Setup ---"
PROJ=$(curl -s "${H[@]}" -X POST "$BASE/projects" -d '{"name":"demo-t127"}')
PID=$(echo "$PROJ" | j "['id']")
API_KEY=$(echo "$PROJ" | j "['api_key']")
AH=(-H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json")

E1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics" -d '{"title":"Agent Infra"}' | j "['id']")
F1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/epics/$E1/features" -d '{"title":"Task Assignment"}' | j "['id']")
T1=$(curl -s "${H[@]}" -X POST "$BASE/projects/$PID/features/$F1/tasks" -d '{"title":"Implement assign endpoint"}' | j "['id']")
echo "Created project, epic, feature, task"

echo ""
echo "--- 1. Register an agent ---"
REG=$(curl -s "${AH[@]}" -X POST "$BASE/agents/register" -d '{"worktree_path":"/repo/wt-target","branch_name":"wt-target"}')
WT_ID=$(echo "$REG" | j "['worktree_id']")
echo "Registered worktree: $WT_ID"

echo ""
echo "--- 2. Assign task to agent (PATCH /agents/{wt}/assign-task) ---"
RESULT=$(curl -s "${H[@]}" -X PATCH "$BASE/agents/$WT_ID/assign-task" -d "{\"task_id\":\"$T1\"}")
echo "$RESULT" | python3 -c "
import sys, json; d=json.load(sys.stdin)
assert d['status'] == 'assigned', f'Expected assigned, got {d[\"status\"]}'
print(f'task_id={d[\"task_id\"]}')
print(f'worktree_id={d[\"worktree_id\"]}')
print(f'status={d[\"status\"]}')
print('PASS: Task assigned without status change')
"

echo ""
echo "--- 3. Verify task in get_my_tasks ---"
curl -s "${H[@]}" "$BASE/agents/$WT_ID/tasks" | python3 -c "
import sys, json; tasks=json.load(sys.stdin)
assert len(tasks) == 1, f'Expected 1 task, got {len(tasks)}'
print(f'Task: {tasks[0][\"title\"]} [{tasks[0][\"status\"]}]')
assert tasks[0]['status'] != 'in_progress', 'Status should NOT be in_progress'
print('PASS: Task visible in get_my_tasks, status unchanged')
"

echo ""
echo "--- 4. Heartbeat delivers notification ---"
curl -s "${AH[@]}" -X POST "$BASE/agents/$WT_ID/heartbeat" | python3 -c "
import sys, json; d=json.load(sys.stdin)
msgs = d['pending_messages']
assert len(msgs) == 1, f'Expected 1 message, got {len(msgs)}'
assert 'New task assigned' in msgs[0], 'Missing assignment notification'
print(f'Message: {msgs[0]}')
print('PASS: Notification delivered via heartbeat')
"

echo ""
echo "--- 5. 404 for unknown worktree ---"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" -X PATCH "$BASE/agents/00000000-0000-0000-0000-000000000000/assign-task" -d "{\"task_id\":\"$T1\"}")
echo "HTTP $STATUS"
[ "$STATUS" = "404" ] && echo "PASS: Unknown worktree returns 404" || echo "FAIL"

echo ""
echo "=== All assertions passed ==="
