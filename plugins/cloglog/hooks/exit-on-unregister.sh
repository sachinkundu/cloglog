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

# T-428: target resolution. The hook's prior strategy was `CLAUDE_PID=$PPID`
# — but $PPID is whatever shell claude used to spawn the hook (sh -c, bash
# -c, or a direct exec into the script), which on 2026-05-05 was observed
# to either be a transient wrapper that exited before the kill landed, or
# a process whose single TERM was insufficient to bring claude down (5
# deterministic recurrences in one supervisor session: close-wave work
# logs t394, t354, t437, t438). The launcher now writes
# `<worktree>/.cloglog/claude.pid` after backgrounding claude
# (templates/launch.sh.template). Prefer that file; fall back to $PPID for
# back-compat with launchers that have not been re-rendered yet.
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
CLAUDE_PID=""
if [[ -n "$CWD" ]]; then
  WORKTREE_ROOT=$(cd "$CWD" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null) || WORKTREE_ROOT=""
  if [[ -n "$WORKTREE_ROOT" ]] && [[ -r "$WORKTREE_ROOT/.cloglog/claude.pid" ]]; then
    PID_FROM_FILE=$(cat "$WORKTREE_ROOT/.cloglog/claude.pid" 2>/dev/null | tr -d '[:space:]')
    if [[ "$PID_FROM_FILE" =~ ^[0-9]+$ ]] && kill -0 "$PID_FROM_FILE" 2>/dev/null; then
      CLAUDE_PID="$PID_FROM_FILE"
    fi
  fi
fi
PID_SOURCE="pidfile"
if [[ -z "$CLAUDE_PID" ]]; then
  CLAUDE_PID=$PPID
  PID_SOURCE="ppid"
fi

# T-428: escalating signal sequence. A single TERM was insufficient on
# 2026-05-05 — claude's Node process either trapped TERM with cleanup
# logic that didn't exit, or the kill went to a wrapper that died
# leaving claude orphaned and alive. Escalate: TERM → 4s → INT (Ctrl-C
# equivalent, the signal claude's TUI is built to handle) → 4s → KILL.
# Log every step so post-incident investigators can see exactly how far
# the escalation went. setsid + disown detaches the watcher from this
# shell so it survives our exit.
LOG=/tmp/agent-shutdown-debug.log
setsid bash -c "
  PID=$CLAUDE_PID
  log() { echo \"[\$(date -Iseconds)] exit-on-unregister.sh \$1 pid=\$PID source=$PID_SOURCE\" >> $LOG 2>&1 || true; }
  sleep 2
  kill -0 \$PID 2>/dev/null || { log 'parent already gone before TERM'; exit 0; }
  kill -TERM \$PID 2>/dev/null && log 'sent TERM' || log 'TERM failed'
  for _ in 1 2 3 4; do sleep 1; kill -0 \$PID 2>/dev/null || { log 'died after TERM'; exit 0; }; done
  kill -INT \$PID 2>/dev/null && log 'escalated to INT' || log 'INT failed'
  for _ in 1 2 3 4; do sleep 1; kill -0 \$PID 2>/dev/null || { log 'died after INT'; exit 0; }; done
  kill -KILL \$PID 2>/dev/null && log 'escalated to KILL' || log 'KILL failed'
" </dev/null >/dev/null 2>&1 &
disown

{
  echo "[$(date -Iseconds)] exit-on-unregister.sh scheduled escalating kill claude_pid=$CLAUDE_PID source=$PID_SOURCE"
} >> /tmp/agent-shutdown-debug.log 2>&1 || true

exit 0
