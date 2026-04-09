# Fix: Agent Token No-Rotate — Demo

Proves that re-registration does not invalidate existing agent tokens.

## Setup: create project

```bash
PROJECT=$(curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" \
  -d '{"name": "demo-token-'$(date +%s)'", "repo_url": "https://github.com/test/demo"}')
API_KEY=$(echo "$PROJECT" | jq -r .api_key)
PID=$(echo "$PROJECT" | jq -r .id)
echo "API key: ${API_KEY:0:8}..."
```

## First registration — get a token

```bash
WT_PATH="/tmp/demo-token-$(date +%s)"
REG1=$(curl -s -X POST http://localhost:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d "{\"worktree_path\": \"$WT_PATH\", \"branch_name\": \"demo\"}")
WT_ID=$(echo "$REG1" | jq -r .worktree_id)
TOKEN=$(echo "$REG1" | jq -r .agent_token)
echo "Token: ${TOKEN:0:8}..."
echo "Resumed: $(echo "$REG1" | jq -r .resumed)"
echo "agent_token present: $(echo "$REG1" | jq 'has("agent_token") and .agent_token != null')"
```

Expected: `Resumed: false`, `agent_token present: true`

## Heartbeat works with the token

```bash
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/heartbeat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq '{status, shutdown_requested}'
```

Expected: `{"status": "ok", "shutdown_requested": false}`

## Re-register (reconnect) — token is NOT rotated

```bash
REG2=$(curl -s -X POST http://localhost:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d "{\"worktree_path\": \"$WT_PATH\", \"branch_name\": \"demo\"}")
echo "Resumed: $(echo "$REG2" | jq -r .resumed)"
echo "agent_token: $(echo "$REG2" | jq -r .agent_token)"
```

Expected: `Resumed: true`, `agent_token: null` — no new token issued on reconnect.

## Original token STILL works after reconnect

```bash
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/heartbeat" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq '{status, shutdown_requested}'
```

Expected: `{"status": "ok", "shutdown_requested": false}` — the original token was NOT invalidated.

## Cleanup

```bash
curl -s -X POST "http://localhost:8000/api/v1/agents/$WT_ID/unregister" \
  -H "Authorization: Bearer $TOKEN" -o /dev/null -w "Unregister: HTTP %{http_code}\n"
curl -s -X DELETE "http://localhost:8000/api/v1/projects/$PID" \
  -H "X-Dashboard-Key: cloglog-dashboard-dev" -o /dev/null -w "Delete project: HTTP %{http_code}\n"
```
