#!/bin/bash
# PostToolUse:Bash — remind to update board and confirm inbox monitor when a PR is created.
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
    echo "2. Confirm your .cloglog/inbox Monitor is running (tail -n 0 -F <WORKTREE_PATH>/.cloglog/inbox)."
    echo "   GitHub webhooks deliver review/CI/merge events sub-second to your inbox."
    echo "   Do NOT start a /loop — the inbox Monitor is the signal source."
    echo ""
    echo "When the pr_merged inbox event arrives, run the per-task shutdown sequence:"
    echo "  (1) emit pr_merged_notification to main inbox"
    echo "  (2) call mark_pr_merged"
    echo "  (3) for spec/plan tasks: call report_artifact"
    echo "  (4) write shutdown-artifacts/work-log-T-<TASK_NUM>.md"
    echo "      (TASK_NUM is your active task's 'number' field from get_my_tasks/start_task,"
    echo "       NOT the PR number — T-42 and PR #317 are different things)"
    echo "  (5) build aggregate shutdown-artifacts/work-log.md"
    echo "  (6) emit agent_unregistered with reason='pr_merged'"
    echo "  (7) call unregister_agent and exit"
    echo "  The supervisor handles relaunching for subsequent tasks."
fi
