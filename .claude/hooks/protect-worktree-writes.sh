#!/bin/bash
# Enforce worktree discipline: agents on wt-* branches can only write to their assigned directories.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')
BRANCH=$(cd "$CWD" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

# Not a worktree branch — allow everything
if [[ "$BRANCH" != wt-* ]]; then
  exit 0
fi

# Only validate file-writing tools
if [[ ! "$TOOL_NAME" =~ ^(Edit|Write)$ ]]; then
  exit 0
fi

# No file path — allow (shouldn't happen)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Extract worktree name (e.g., "board" from "wt-board")
WORKTREE_NAME="${BRANCH#wt-}"

# Define allowed directories per worktree
case "$WORKTREE_NAME" in
  board)       ALLOWED=("src/board/" "tests/board/" "src/alembic/") ;;
  agent)       ALLOWED=("src/agent/" "tests/agent/" "src/alembic/") ;;
  document)    ALLOWED=("src/document/" "tests/document/" "src/alembic/") ;;
  gateway*)    ALLOWED=("src/gateway/" "tests/gateway/" "src/shared/") ;;
  frontend*)   ALLOWED=("frontend/") ;;
  mcp*)        ALLOWED=("mcp-server/") ;;
  assign*)     ALLOWED=("src/gateway/" "src/board/" "tests/gateway/" "tests/board/") ;;
  e2e*)        ALLOWED=("tests/e2e/") ;;
  *)           exit 0 ;;  # Unknown worktree pattern — don't block
esac

# Normalize file path to be relative to CWD
REL_PATH="${FILE_PATH#$CWD/}"

for pattern in "${ALLOWED[@]}"; do
  if [[ "$REL_PATH" == $pattern* ]]; then
    exit 0  # Allowed
  fi
done

echo "Blocked: Branch '$BRANCH' can only write to: ${ALLOWED[*]}" >&2
echo "Attempted write to: $REL_PATH" >&2
exit 2
