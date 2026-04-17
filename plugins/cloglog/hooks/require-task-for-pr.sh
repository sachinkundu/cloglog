#!/bin/bash
# PreToolUse hook: remind agent to create a board task before creating a PR.
# This is advisory enforcement — it prints a strong warning rather than blocking,
# because the hook can't reliably query the board from a shell script without
# knowing the worktree UUID.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[[ "$TOOL_NAME" == "Bash" ]] || exit 0
echo "$COMMAND" | grep -qE 'gh pr create' || exit 0

# Print a strong reminder — this appears in the agent's context
cat >&2 << 'MSG'
REMINDER: Every PR must have a board task.

Before creating this PR, verify:
1. You have a board task in_progress (via mcp__cloglog__start_task)
2. After creating the PR, immediately set pr_url on the task (via mcp__cloglog__update_task_status to review)

Without a task, webhook notifications (merge, review, CI) will not reach you.
MSG

exit 0
