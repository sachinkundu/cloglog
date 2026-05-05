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

# T-475: breadcrumb written unconditionally — lets investigators confirm the
# hook FIRED even when a guard exits early (the "scheduled" log only appears
# after all conditions pass). This mirrors the agent-shutdown.sh breadcrumb
# that caught "hook never ran" vs "hook ran but conditions failed" on T-217.
LOG="${CLOGLOG_SHUTDOWN_LOG:-/tmp/agent-shutdown-debug.log}"
{
  echo "[$(date -Iseconds)] exit-on-unregister.sh fired"
} >> "$LOG" 2>&1 || true

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

# T-428 / T-475: target resolution — three strategies in priority order.
#
# Strategy 1 (T-428): read from <worktree>/.cloglog/claude.pid written by
# launch.sh after backgrounding claude. Reliable for any worktree created
# after T-428 shipped (launch.sh.template writes the file; hook reads it).
#
# Strategy 2 (T-475): walk the process tree from $PPID looking for a
# process with --dangerously-skip-permissions in its args. launch.sh always
# invokes: claude --dangerously-skip-permissions ... . The hook is a child
# of claude through at most one or two shell wrappers. Walking up a few
# levels finds claude before the wrapper exits — hooks run synchronously,
# so the wrapper is alive during the walk. This catches old worktrees
# (created before T-428) whose launch.sh does not write the pidfile.
# Root cause of 2026-05-05 regression (wt-t430/t432/t435): those worktrees
# had the T-352 hook (just $PPID, no pidfile, no tree-walk) — $PPID was
# a transient wrapper that exited before the killer woke up, so the setsid
# process saw "parent already gone" and exited, leaving claude alive.
#
# Strategy 3: $PPID as last resort. May be a transient wrapper, not claude.
# Escalating TERM→INT→KILL still applies and may succeed if $PPID IS claude.
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
CLAUDE_PID=""
PID_SOURCE=""

# Strategy 1: pidfile
if [[ -n "$CWD" ]]; then
  WORKTREE_ROOT=$(cd "$CWD" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null) || WORKTREE_ROOT=""
  if [[ -n "$WORKTREE_ROOT" ]] && [[ -r "$WORKTREE_ROOT/.cloglog/claude.pid" ]]; then
    PID_FROM_FILE=$(cat "$WORKTREE_ROOT/.cloglog/claude.pid" 2>/dev/null | tr -d '[:space:]')
    if [[ "$PID_FROM_FILE" =~ ^[0-9]+$ ]] && kill -0 "$PID_FROM_FILE" 2>/dev/null; then
      CLAUDE_PID="$PID_FROM_FILE"
      PID_SOURCE="pidfile"
    fi
  fi
fi

# Strategy 2: process tree walk
if [[ -z "$CLAUDE_PID" ]]; then
  _walk_pid=$PPID
  _walk_level=0
  while [[ $_walk_level -lt 5 ]] && [[ -n "$_walk_pid" ]] && [[ "$_walk_pid" -gt 1 ]]; do
    _walk_cmd=$(ps -o args= -p "$_walk_pid" 2>/dev/null || true)
    if [[ "$_walk_cmd" == *"dangerously-skip-permissions"* ]] && kill -0 "$_walk_pid" 2>/dev/null; then
      CLAUDE_PID="$_walk_pid"
      PID_SOURCE="tree-walk-l${_walk_level}"
      break
    fi
    _walk_next=$(ps -o ppid= -p "$_walk_pid" 2>/dev/null | tr -d '[:space:]' || true)
    if [[ -z "$_walk_next" ]] || [[ "$_walk_next" == "$_walk_pid" ]]; then
      break
    fi
    _walk_pid="$_walk_next"
    ((_walk_level++))
  done
fi

# Strategy 3: $PPID fallback
if [[ -z "$CLAUDE_PID" ]]; then
  CLAUDE_PID=$PPID
  PID_SOURCE="ppid-fallback"
fi

# T-428: escalating signal sequence. A single TERM was insufficient on
# 2026-05-05 — claude's Node process either trapped TERM with cleanup
# logic that didn't exit, or the kill went to a wrapper that died
# leaving claude orphaned and alive. Escalate: TERM → 4s → INT (Ctrl-C
# equivalent, the signal claude's TUI is built to handle) → 4s → KILL.
# Log every step so post-incident investigators can see exactly how far
# the escalation went. setsid + disown detaches the watcher from this
# shell so it survives our exit.
setsid bash -c "
  PID=$CLAUDE_PID
  LOG=$LOG
  log() { echo \"[\$(date -Iseconds)] exit-on-unregister.sh \$1 pid=\$PID source=$PID_SOURCE\" >> \$LOG 2>&1 || true; }
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
} >> "$LOG" 2>&1 || true

exit 0
