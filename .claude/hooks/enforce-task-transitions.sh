#!/bin/bash
# Enforce task status transitions: done requires review first.
# Valid flow: backlog → in_progress → review → done

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')

# Only intercept the MCP update_task_status and complete_task tools
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

# Query current task status from the API
BOARD_JSON=$(curl -s "http://localhost:8000/api/v1/projects/4d9e825a-c911-4110-bcd5-9072d1887813/board" 2>/dev/null)
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
