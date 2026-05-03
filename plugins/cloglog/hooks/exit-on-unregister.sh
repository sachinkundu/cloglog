#!/bin/bash
# T-352: PostToolUse hook on mcp__cloglog__unregister_agent.
#
# Without this hook, an agent that completes the per-task shutdown sequence
# (emit agent_unregistered → call unregister_agent → "exit") leaves claude
# running interactively waiting for the next user input. The launcher
# (plugins/cloglog/skills/launch/SKILL.md) backgrounds claude and `wait`s on
# its PID; with claude alive the launcher never returns, the supervisor sees
# the worktree as "still running" until it force-closes the zellij tab.
# Reproduced on wt-t377-ci-trigger 2026-05-02 and wt-codex-review-fixes
# 2026-05-03 after the T-374 PR #296 merge.
#
# Fix: after a *successful* unregister_agent tool call, schedule a TERM to
# the claude process. Claude's SessionEnd hook fires (best-effort backstop;
# the cooperative path already cleared backend state), claude exits, the
# launcher's `wait` completes, the launcher returns 0. The zellij tab stays
# open for the supervisor — close-wave Step 7 / reconcile Step 5 still own
# tab teardown, and that path is unaffected.
#
# Why we DO NOT kill on a failed unregister: agent-lifecycle.md §4.1 routes
# any 4xx/5xx through the mcp_tool_error escalation flow (write the error
# to the supervisor inbox and wait for guidance). Killing claude would
# erase that wait-state and lose the failure signal.

set -u

INPUT=$(cat /dev/stdin 2>/dev/null || echo "{}")
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)

if [[ "$TOOL_NAME" != "mcp__cloglog__unregister_agent" ]]; then
  exit 0
fi

# unregister_agent's success response is `{ content: [{ type: "text",
# text: "Unregistered <wt>." }] }` (mcp-server/src/server.ts:165). On
# error the SDK either sets isError=true on the response or returns a
# JSON-RPC error envelope; in either case the success-text shape is
# absent. Match the prefix to be defensive against future text changes.
RESPONSE_TEXT=$(echo "$INPUT" | jq -r '.tool_response.content[0].text // empty' 2>/dev/null)
IS_ERROR=$(echo "$INPUT" | jq -r '.tool_response.isError // .tool_response.is_error // false' 2>/dev/null)

if [[ "$IS_ERROR" == "true" ]]; then
  exit 0
fi

if [[ "$RESPONSE_TEXT" != Unregistered* ]]; then
  exit 0
fi

# The hook is a subprocess of claude — $PPID is claude's PID. Capture it
# before forking so the watcher reads the right value even if its own
# PPID changes after disown.
CLAUDE_PID=$PPID

# Background watcher: short delay so this hook's MCP tool response can
# flush back through the transport, then TERM claude. setsid + disown
# detaches the watcher from this shell so it survives our exit.
setsid bash -c "sleep 2; kill -TERM $CLAUDE_PID 2>/dev/null" \
  </dev/null >/dev/null 2>&1 &
disown

{
  echo "[$(date -Iseconds)] exit-on-unregister.sh scheduled TERM claude_pid=$CLAUDE_PID"
} >> /tmp/agent-shutdown-debug.log 2>&1 || true

exit 0
