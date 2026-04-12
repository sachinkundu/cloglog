#!/bin/bash
# PreToolUse hook: remind to use MCP tools instead of direct API calls.
# Reads backend_url from .cloglog/config.yaml to know what to block.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Only check Bash tool calls
[[ "$TOOL_NAME" == "Bash" ]] || exit 0
[[ -n "$COMMAND" ]] || exit 0

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

BACKEND_URL=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$CONFIG'))
print(cfg.get('backend_url', 'http://localhost:8000'))
" 2>/dev/null) || exit 0

# Strip protocol for pattern matching (e.g. "localhost:8000")
BACKEND_HOST=$(echo "$BACKEND_URL" | sed 's|https\?://||')

# Check if the command hits the backend API directly
if echo "$COMMAND" | grep -qE "curl.*${BACKEND_HOST}/api|wget.*${BACKEND_HOST}/api"; then
  # Allow if it's clearly a test or debugging command
  if echo "$COMMAND" | grep -qiE 'test|debug|verify|check.*status'; then
    exit 0
  fi
  echo "Blocked: Use MCP tools (mcp__cloglog__*) instead of direct API calls." >&2
  echo "Available MCP tools: get_board, get_backlog, list_epics, list_features," >&2
  echo "create_task, update_task_status, complete_task, delete_task, etc." >&2
  exit 2
fi

exit 0
