#!/bin/bash
# PreToolUse hook: enforce task status transitions — done requires review first.
# Reads backend_url and project_id from .cloglog/config.yaml.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Only intercept MCP update_task_status and complete_task tools
case "$TOOL_NAME" in
  mcp__cloglog__update_task_status) ;;
  mcp__cloglog__complete_task) ;;
  *) exit 0 ;;
esac

TARGET_STATUS=$(echo "$INPUT" | jq -r '.tool_input.status // empty')
TASK_ID=$(echo "$INPUT" | jq -r '.tool_input.task_id // empty')

[[ -n "$TASK_ID" ]] || exit 0

# complete_task always moves to done
if [[ "$TOOL_NAME" == "mcp__cloglog__complete_task" ]]; then
  TARGET_STATUS="done"
fi

# Only enforce the done transition
[[ "$TARGET_STATUS" == "done" ]] || exit 0

# --- Find config ---
find_config() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.cloglog/config.yaml" ]]; then
      echo "$dir/.cloglog/config.yaml"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  local repo_root
  repo_root=$(cd "$1" && git rev-parse --show-toplevel 2>/dev/null) || return 1
  if [[ -f "$repo_root/.cloglog/config.yaml" ]]; then
    echo "$repo_root/.cloglog/config.yaml"
    return 0
  fi
  return 1
}

CONFIG=$(find_config "$CWD") || exit 0

# T-312: parse via shared stdlib helper, NEVER the python YAML lib.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/parse-yaml-scalar.sh
source "${HOOK_DIR}/lib/parse-yaml-scalar.sh"
BACKEND_URL=$(read_yaml_scalar "$CONFIG" "backend_url" "http://localhost:8000")
PROJECT_ID=$(read_yaml_scalar "$CONFIG" "project_id" "")

# No project_id — can't verify, allow
[[ -n "$PROJECT_ID" ]] || exit 0

# Query current task status from the API
BOARD_JSON=$(curl -s "${BACKEND_URL}/api/v1/projects/${PROJECT_ID}/board" 2>/dev/null)
if [[ -z "$BOARD_JSON" ]]; then
  echo "Blocked: Backend is unreachable — cannot verify task status." >&2
  exit 2
fi

CURRENT_STATUS=$(echo "$BOARD_JSON" | jq -r --arg tid "$TASK_ID" '
  .columns[].tasks[] | select(.id == $tid) | .status
' 2>/dev/null)

if [[ -z "$CURRENT_STATUS" ]]; then
  # Task not found on board — allow (might be a different project)
  exit 0
fi

if [[ "$CURRENT_STATUS" != "review" ]]; then
  echo "Blocked: Cannot move task to 'done' — current status is '$CURRENT_STATUS', must be 'review' first." >&2
  echo "Move the task to 'review' and get user confirmation before marking done." >&2
  exit 2
fi

exit 0
