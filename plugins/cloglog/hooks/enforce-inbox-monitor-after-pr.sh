#!/bin/bash
# PostToolUse hook (T-370): block the agent's next action when `gh pr create`
# completed without an active inbox Monitor on the relevant .cloglog/inbox.
#
# The github-bot SKILL mandates arming a Monitor on <worktree>/.cloglog/inbox
# immediately after every PR creation. This hook enforces that rule at the
# harness layer so a missed step becomes a hard block on the next tool call,
# not a silent skip (the 2026-05-02 PR #285 incident — main agent skipped the
# monitor-arm and missed a codex MEDIUM finding for ~30 minutes).
#
# Inbox path resolution (same shape the github-bot SKILL uses):
#   1. `git -C <cwd> rev-parse --show-toplevel` → current worktree root
#   2. `git -C <cwd> rev-parse --path-format=absolute --git-common-dir`
#      dirname → main project root
#   3. If worktree root == main project root → main session; inbox is
#      at <project_root>/.cloglog/inbox.
#      Otherwise → worktree session; inbox is at <worktree_root>/.cloglog/inbox.
#
# Monitor detection:
#   Check `ps -ww -eo args` for a process whose command line contains both
#   "tail" and the resolved inbox path. Claude Code's Monitor tool spawns a
#   persistent `tail -n 0 -F <path>` subprocess; that subprocess remains
#   visible in the process list for the lifetime of the monitor.
#
# Failure modes:
#   Any inspection failure (git unavailable, ps unavailable, not a git repo)
#   surfaces as a warning with exit 2. No silent auto-pass on unknown state.

set -u

INPUT=$(cat /dev/stdin 2>/dev/null || echo "{}")
TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)

# Only fire on Bash tool uses containing 'gh pr create'
[[ "$TOOL_NAME" == "Bash" ]] || exit 0
printf '%s' "$COMMAND" | grep -qE '\bgh pr create\b' || exit 0

# Only fire when a PR was actually created — mirror remind-pr-update.sh:
# extract the PR URL from the tool response; if absent the command failed
# (auth error, --dry-run, GitHub validation error) and no monitor is needed.
TOOL_RESPONSE=$(printf '%s' "$INPUT" | jq -r '.tool_response // empty' 2>/dev/null)
PR_URL=$(printf '%s' "$TOOL_RESPONSE" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1)
[[ -n "$PR_URL" ]] || exit 0

# ── Resolve inbox path ────────────────────────────────────────────────────
LOOKUP_DIR="${CWD:-$PWD}"

WORKTREE_ROOT=$(git -C "$LOOKUP_DIR" rev-parse --show-toplevel 2>/dev/null) || {
    cat >&2 << 'MSG'
⚠ enforce-inbox-monitor: cannot resolve git worktree root from CWD.
Cannot verify inbox monitor state — arm the monitor manually before continuing:

  Monitor(
    command="mkdir -p <worktree>/.cloglog && touch <worktree>/.cloglog/inbox && tail -n 0 -F <worktree>/.cloglog/inbox",
    description="Worktree inbox events",
    persistent=true
  )
MSG
    exit 2
}

GIT_COMMON_DIR=$(git -C "$LOOKUP_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || {
    cat >&2 << 'MSG'
⚠ enforce-inbox-monitor: cannot resolve git-common-dir. Cannot determine
whether this is a worktree or the main checkout. Arm inbox monitor manually.
MSG
    exit 2
}

PROJECT_ROOT=$(dirname "$GIT_COMMON_DIR")

if [[ "$WORKTREE_ROOT" == "$PROJECT_ROOT" ]]; then
    # Main checkout — inbox lives at the project root
    INBOX_PATH="${PROJECT_ROOT}/.cloglog/inbox"
else
    # Inside a worktree — inbox lives at the worktree root
    INBOX_PATH="${WORKTREE_ROOT}/.cloglog/inbox"
fi

# ── Detect running inbox monitor ──────────────────────────────────────────
PS_OUTPUT=$(ps -ww -eo pid=,args= 2>/dev/null) || {
    cat >&2 << 'MSG'
⚠ enforce-inbox-monitor: `ps -ww -eo pid=,args=` failed — cannot inspect
running processes. Arm inbox monitor manually before continuing.
MSG
    exit 2
}

# Canonical form: absolute inbox path in process args (strip leading PID first).
PS_ARGS=$(printf '%s\n' "$PS_OUTPUT" | awk '{$1=""; print}')
if printf '%s\n' "$PS_ARGS" | grep -F "$INBOX_PATH" | grep -qF "tail"; then
    exit 0
fi

# Legacy form: relative .cloglog/inbox path (tail -f .cloglog/inbox), documented
# in the setup/github-bot SKILLs for dedupe and crash-recovery flows.
# On Linux, use /proc/<pid>/cwd to verify the process runs from the resolved
# worktree or project root — prevents a relative-path tail in an unrelated
# checkout from satisfying the check for the current agent's inbox.
if [[ -d "/proc/1" ]]; then
    while IFS= read -r line; do
        pid=$(printf '%s' "$line" | awk '{print $1}')
        [[ "$pid" =~ ^[0-9]+$ ]] || continue
        proc_cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null) || continue
        if [[ "$proc_cwd" == "$WORKTREE_ROOT" || "$proc_cwd" == "$PROJECT_ROOT" ]]; then
            exit 0
        fi
    done < <(printf '%s\n' "$PS_OUTPUT" | grep -E "[[:space:]]tail[[:print:]]*[[:space:]]\.cloglog/inbox")
else
    # Non-Linux: /proc unavailable, accept any relative-form match.
    if printf '%s\n' "$PS_ARGS" | grep -qE "tail[[:print:]]*[[:space:]]\.cloglog/inbox"; then
        exit 0
    fi
fi

INBOX_DIR=$(dirname "$INBOX_PATH")
cat >&2 << MSG
⛔ PR created but no inbox monitor is running on:
  ${INBOX_PATH}

Without an active Monitor, review comments, CI failures, and merge
notifications land silently in the inbox file and you will never react.
Arm the monitor NOW before doing anything else:

  Monitor(
    command="mkdir -p ${INBOX_DIR} && touch ${INBOX_PATH} && tail -n 0 -F ${INBOX_PATH}",
    description="Worktree inbox events",
    persistent=true
  )
MSG
exit 2
