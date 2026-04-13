#!/bin/bash
# PostToolUse:Bash — remind to update board and set up PR polling loop when a PR is created.
# Detects gh pr create output and reminds the agent about BOTH required next steps.

INPUT=$(cat /dev/stdin 2>/dev/null || echo "{}")
TOOL_OUTPUT=$(echo "$INPUT" | jq -r '.tool_response // empty' 2>/dev/null)

# Check if the output contains a GitHub PR URL
PR_URL=$(echo "$TOOL_OUTPUT" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1)

if [ -n "$PR_URL" ]; then
    PR_NUM=$(echo "$PR_URL" | grep -oE '[0-9]+$')
    echo "PR created: $PR_URL"
    echo ""
    echo "TWO things you MUST do now:"
    echo "1. Call update_task_status to move the active task to review with this PR URL"
    echo "2. Set up the PR polling loop:"
    echo "   /loop 5m Check PR #${PR_NUM} for review comments, CI status, and merge state using the github-bot skill. If new comments: move task to in_progress, address feedback, push fix, move back to review. If merged: call get_my_tasks and start the next task."
    echo ""
    echo "If you skip step 2, you will NEVER know when the PR is merged or has review comments."
fi
