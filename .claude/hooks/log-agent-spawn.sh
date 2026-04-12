#!/bin/bash
# Log every Agent tool invocation for telemetry.
# Records: timestamp, subagent type, description, parent working directory.

INPUT=$(cat)
SUBAGENT=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // "general-purpose"' 2>/dev/null)
DESC=$(echo "$INPUT" | jq -r '.tool_input.description // "unnamed"' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // "unknown"' 2>/dev/null)
WORKTREE=$(basename "$CWD")

LOG_DIR="${CWD}/.claude"
# Fall back to repo root if .claude doesn't exist in cwd
[[ -d "$LOG_DIR" ]] || LOG_DIR="$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null)/.claude"
[[ -d "$LOG_DIR" ]] || exit 0

LOG_FILE="${LOG_DIR}/agent-usage.log"
echo "$(date -Iseconds) | ${SUBAGENT} | ${DESC} | ${WORKTREE}" >> "$LOG_FILE"

exit 0
