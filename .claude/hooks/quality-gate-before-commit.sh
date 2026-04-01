#!/bin/bash
# Enforce quality gate: make quality must pass before git commit/push/PR.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Only validate Bash tool calls
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

# Check if this is a commit, push, or PR command
if ! echo "$COMMAND" | grep -qE '(git commit|git push|gh pr create)'; then
  exit 0
fi

# Run quality checks
cd "$CWD" || exit 0

if ! make quality > /tmp/quality-check-$$.log 2>&1; then
  echo "Blocked: 'make quality' failed. Fix issues before committing." >&2
  echo "---" >&2
  tail -20 /tmp/quality-check-$$.log >&2
  rm -f /tmp/quality-check-$$.log
  exit 2
fi

rm -f /tmp/quality-check-$$.log
exit 0
