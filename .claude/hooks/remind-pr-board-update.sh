#!/bin/bash
# PostToolUse:Bash — remind to update board when a PR is created
# Detects gh pr create output and reminds the agent to move the task to review.

# Tool output comes via JSON on stdin
INPUT=$(cat /dev/stdin 2>/dev/null || echo "{}")
TOOL_OUTPUT=$(echo "$INPUT" | jq -r '.tool_response // empty' 2>/dev/null)

# Check if the output contains a GitHub PR URL (gh pr create prints the URL on success)
PR_URL=$(echo "$TOOL_OUTPUT" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1)

if [ -n "$PR_URL" ]; then
    echo "⚠️ PR created: $PR_URL — update the board: call update_task_status to move the active task to review with this PR URL."
fi
