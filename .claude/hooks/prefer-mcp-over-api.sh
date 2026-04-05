#!/bin/bash
# PreToolUse hook: remind to use MCP tools instead of direct API calls.
# Blocks curl/wget commands that hit the cloglog API.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only check Bash tool calls
[[ "$TOOL_NAME" == "Bash" ]] || exit 0
[[ -n "$COMMAND" ]] || exit 0

# Check if the command hits the cloglog API directly
if echo "$COMMAND" | grep -qE 'curl.*localhost:8000/api|wget.*localhost:8000/api'; then
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
