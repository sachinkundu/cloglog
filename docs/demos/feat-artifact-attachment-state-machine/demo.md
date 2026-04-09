# Artifact Attachment State Machine — Demo

Exercises the `report_artifact` endpoint and pipeline guard against the live backend.

## Setup: create project, epic, feature, spec task

```bash
# Create a demo project
PROJECT=$(curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -d '{"name": "demo-artifact-'$(date +%s)'", "repo_url": "https://github.com/test/demo"}')
PID=$(echo "$PROJECT" | jq -r .id)
API_KEY=$(echo "$PROJECT" | jq -r .api_key)

# Create epic → feature → spec task + plan task
EPIC=$(curl -s -X POST "http://localhost:8000/api/v1/projects/$PID/epics" \
  -H "Content-Type: application/json" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -d '{"title": "Demo Epic"}')
EID=$(echo "$EPIC" | jq -r .id)

FEAT=$(curl -s -X POST "http://localhost:8000/api/v1/projects/$PID/epics/$EID/features" \
  -H "Content-Type: application/json" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -d '{"title": "Demo Feature"}')
FID=$(echo "$FEAT" | jq -r .id)

SPEC=$(curl -s -X POST "http://localhost:8000/api/v1/projects/$PID/features/$FID/tasks" \
  -H "Content-Type: application/json" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -d '{"title": "Write spec", "task_type": "spec"}')
SPEC_ID=$(echo "$SPEC" | jq -r .id)

PLAN=$(curl -s -X POST "http://localhost:8000/api/v1/projects/$PID/features/$FID/tasks" \
  -H "Content-Type: application/json" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -d '{"title": "Write plan", "task_type": "plan"}')
PLAN_ID=$(echo "$PLAN" | jq -r .id)

echo "Project: $PID"
echo "Feature: $FID"
echo "Spec task: $SPEC_ID"
echo "Plan task: $PLAN_ID"
```

## Register agent, start spec, move to review

```bash
# Register agent
REG=$(curl -s -X POST http://localhost:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"worktree_path": "/tmp/demo-wt-'$(date +%s)'", "branch_name": "demo"}')
WT_ID=$(echo "$REG" | jq -r .worktree_id)
AGENT_TOKEN=$(echo "$REG" | jq -r .agent_token)
echo "Worktree: $WT_ID"
echo "Agent token: ${AGENT_TOKEN:0:8}..."

# Start spec task
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/start-task" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -d "{\"task_id\": \"$SPEC_ID\"}" | jq .

# Move to review with PR URL
curl -s -X PATCH "http://localhost:8000/api/v1/agents/$WT_ID/task-status" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -d "{\"task_id\": \"$SPEC_ID\", \"status\": \"review\", \"pr_url\": \"https://github.com/test/pull/42\"}"
echo "Spec task moved to review"
```

## Demo 1: Pipeline blocks plan when spec has no artifact

```bash
# Try to start plan task — should be BLOCKED (spec has no artifact)
echo "=== Attempting to start plan without artifact ==="
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/start-task" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -d "{\"task_id\": \"$PLAN_ID\"}" | jq .
```

## Demo 2: report_artifact on spec task

```bash
# Report artifact — should succeed (spec task in review)
echo "=== Reporting artifact ==="
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/report-artifact" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -d "{\"task_id\": \"$SPEC_ID\", \"artifact_path\": \"docs/specs/F-1-spec.md\"}" | jq .
```

## Demo 3: Pipeline allows plan after artifact attached

```bash
# Now start plan task — should SUCCEED (spec has artifact)
echo "=== Starting plan after artifact attached ==="
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/start-task" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -d "{\"task_id\": \"$PLAN_ID\"}" | jq .
```

## Demo 4: report_artifact rejected on wrong task type

```bash
# Try to report artifact on the plan task (still in_progress, not review) — should fail
echo "=== Attempting artifact on non-review task ==="
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/report-artifact" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  -d "{\"task_id\": \"$PLAN_ID\", \"artifact_path\": \"docs/plans/F-1-plan.md\"}" | jq .
```

## Demo 5: Verify document attached to feature

```bash
# Check documents attached to the feature
echo "=== Documents on feature ==="
curl -s "http://localhost:8000/api/v1/documents?attached_to_type=feature&attached_to_id=$FID" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" | jq '.[] | {title, doc_type, source_path}'
```
