#!/bin/bash
# PreToolUse hook: enforce quality gate before git commit/push/PR.
# Reads quality_command from .cloglog/config.yaml (default: make quality).

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Only validate Bash tool calls
[[ "$TOOL_NAME" == "Bash" ]] || exit 0

# Check if this is a commit, push, or PR command
echo "$COMMAND" | grep -qE '(git commit|git push|gh pr create)' || exit 0

# --- Find project root by walking up from CWD ---
find_config() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.cloglog/config.yaml" ]]; then
      echo "$dir/.cloglog/config.yaml"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  # Also check main repo root for worktrees
  local repo_root
  repo_root=$(cd "$1" && git rev-parse --show-toplevel 2>/dev/null) || return 1
  if [[ -f "$repo_root/.cloglog/config.yaml" ]]; then
    echo "$repo_root/.cloglog/config.yaml"
    return 0
  fi
  return 1
}

CONFIG=$(find_config "$CWD") || exit 0

# T-312: parse via shared stdlib helper, NEVER the python YAML lib.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/parse-yaml-scalar.sh
source "${HOOK_DIR}/lib/parse-yaml-scalar.sh"
QUALITY_CMD=$(read_yaml_scalar "$CONFIG" "quality_command" "make quality")

# Run quality checks
cd "$CWD" || exit 0

if ! $QUALITY_CMD > /tmp/quality-check-$$.log 2>&1; then
  echo "Blocked: '$QUALITY_CMD' failed. Fix issues before committing." >&2
  echo "---" >&2
  tail -20 /tmp/quality-check-$$.log >&2
  rm -f /tmp/quality-check-$$.log
  exit 2
fi

rm -f /tmp/quality-check-$$.log
exit 0
