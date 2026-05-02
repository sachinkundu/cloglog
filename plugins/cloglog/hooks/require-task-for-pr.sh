#!/bin/bash
# PreToolUse hook (T-371): hard-block ``gh pr create`` when no board
# task is in_progress for this working directory's worktree.
#
# Resolution order:
#   1. ``$CLAUDE_PROJECT_DIR/.cloglog/state.json`` if set
#   2. ``$PWD/.cloglog/state.json`` walking up to the filesystem root
#
# state.json is written by ``mcp-server/src/server.ts::register_agent``
# and removed by ``unregister_agent``. Its presence is the proof that
# the current shell sits inside a registered worktree; its absence is
# itself a fail-loud signal — exit 2 with an actionable message that
# tells the agent which MCP call to make.
#
# Pre-T-371 this hook only printed an advisory reminder and exit 0'd.
# That left close-wave runs, force-pushed branches, and one-off
# operator PRs without any board task linkage — verified by the 7
# stale "Close worktree wt-..." rows on F-50 that prompted T-371.

set -u

INPUT=$(cat)
TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty')
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')

[[ "$TOOL_NAME" == "Bash" ]] || exit 0
printf '%s' "$COMMAND" | grep -qE '\bgh pr create\b' || exit 0

# ── Locate state.json ────────────────────────────────────
find_state_file() {
  local start="${1:-$PWD}"
  local dir="$start"
  while [[ "$dir" != "/" && -n "$dir" ]]; do
    if [[ -f "$dir/.cloglog/state.json" ]]; then
      printf '%s\n' "$dir/.cloglog/state.json"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  return 1
}

STATE_FILE=""
if [[ -n "${CLAUDE_PROJECT_DIR:-}" && -f "${CLAUDE_PROJECT_DIR}/.cloglog/state.json" ]]; then
  STATE_FILE="${CLAUDE_PROJECT_DIR}/.cloglog/state.json"
else
  STATE_FILE=$(find_state_file "$PWD") || STATE_FILE=""
fi

if [[ -z "$STATE_FILE" ]]; then
  cat >&2 << 'MSG'
⛔ gh pr create blocked: this working directory has no .cloglog/state.json.

This shell is not registered with the cloglog board. Every PR must have
a board task in_progress before it is opened. To proceed:

  1. Call mcp__cloglog__register_agent(worktree_path=<this worktree>)
  2. Call mcp__cloglog__start_task(<task-uuid>)
  3. Re-run gh pr create
MSG
  exit 2
fi

WORKTREE_ID=$(jq -r '.worktree_id // empty' "$STATE_FILE")
AGENT_TOKEN=$(jq -r '.agent_token // empty' "$STATE_FILE")
BACKEND_URL=$(jq -r '.backend_url // empty' "$STATE_FILE")

if [[ -z "$WORKTREE_ID" || -z "$AGENT_TOKEN" || -z "$BACKEND_URL" ]]; then
  cat >&2 << MSG
⛔ gh pr create blocked: $STATE_FILE is malformed (missing worktree_id /
agent_token / backend_url). Re-register with
mcp__cloglog__register_agent(worktree_path=<this worktree>) and retry.
MSG
  exit 2
fi

# ── Query the gateway for active tasks ──────────────────
RESP=$(curl -sS --max-time 10 \
  -H "Authorization: Bearer ${AGENT_TOKEN}" \
  "${BACKEND_URL%/}/api/v1/agents/${WORKTREE_ID}/tasks" 2>&1) || {
  cat >&2 << MSG
⛔ gh pr create blocked: backend at $BACKEND_URL is unreachable
($RESP). Cannot verify a task is in_progress; refusing to create the PR
without board linkage. Bring the backend up (\`make dev\`) and retry.
MSG
  exit 2
}

# A 4xx/5xx HTML body or JSON detail will not parse as a task array.
IN_PROGRESS_COUNT=$(printf '%s' "$RESP" | jq -r '
  if type == "array" then
    [.[] | select(.status == "in_progress")] | length
  else
    "ERROR"
  end
' 2>/dev/null)

if [[ "$IN_PROGRESS_COUNT" == "ERROR" || -z "$IN_PROGRESS_COUNT" ]]; then
  cat >&2 << MSG
⛔ gh pr create blocked: unexpected response from
${BACKEND_URL%/}/api/v1/agents/${WORKTREE_ID}/tasks. Body:
$RESP
MSG
  exit 2
fi

if [[ "$IN_PROGRESS_COUNT" -lt 1 ]]; then
  BACKLOG_TITLES=$(printf '%s' "$RESP" | jq -r '
    [.[] | select(.status == "backlog") | "T-\(.number) \(.title)"] | .[0:5] | join("\n  - ")
  ' 2>/dev/null)
  cat >&2 << MSG
⛔ gh pr create blocked: no task is in_progress for this worktree.

Every PR must have a board task. Pick one of the backlog tasks below
(or create a new one via mcp__cloglog__create_task) and call
mcp__cloglog__start_task(task_id=<uuid>) before retrying \`gh pr create\`:

  - ${BACKLOG_TITLES:-(none queued — file a task first)}

Without a task, webhook notifications (merge, review, CI) will not
reach you and close-wave / reconcile will surface the PR as orphaned.
MSG
  exit 2
fi

# Success path — keep the historical reminder visible so the agent is
# nudged to set pr_url on the task as soon as the PR is created.
cat >&2 << 'MSG'
✓ Board task in_progress confirmed.

After `gh pr create` succeeds, immediately call
mcp__cloglog__update_task_status(task_id, "review", pr_url=<url>) so
the webhook fan-out can route review/merge/CI events back to you.
MSG
exit 0
