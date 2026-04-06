#!/bin/bash
# Enforce worktree discipline: agents on wt-* branches can only write to their assigned directories.
# Optimized: reads .git/HEAD directly (no subprocess), fast-exits if not on a wt-* branch.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Read branch from .git/HEAD directly — no subprocess overhead
GIT_HEAD="$CWD/.git/HEAD"
[[ -f "$GIT_HEAD" ]] || GIT_HEAD="$CWD/.git"  # worktree uses a file pointing to main repo
if [[ -f "$GIT_HEAD" ]] && head -1 "$GIT_HEAD" | grep -q "^ref:"; then
  BRANCH=$(head -1 "$GIT_HEAD" | sed 's|ref: refs/heads/||')
else
  exit 0  # Detached HEAD or can't read — allow
fi

# Check if we're inside a worktree directory (agents may rename branches to bypass)
WORKTREE_DIR=""
if [[ "$CWD" == */.claude/worktrees/wt-* ]]; then
  WORKTREE_DIR=$(echo "$CWD" | grep -oP '\.claude/worktrees/\Kwt-[^/]+')
fi

# Fast exit: not a worktree branch AND not in a worktree directory
if [[ "$BRANCH" != wt-* ]] && [[ -z "$WORKTREE_DIR" ]]; then
  exit 0
fi

# Use worktree directory name if branch was renamed
if [[ "$BRANCH" != wt-* ]] && [[ -n "$WORKTREE_DIR" ]]; then
  BRANCH="$WORKTREE_DIR"
fi

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[[ -n "$FILE_PATH" ]] || exit 0

WORKTREE_NAME="${BRANCH#wt-}"

case "$WORKTREE_NAME" in
  board)       ALLOWED=("src/board/" "tests/board/" "src/alembic/") ;;
  agent)       ALLOWED=("src/agent/" "tests/agent/" "src/alembic/") ;;
  document)    ALLOWED=("src/document/" "tests/document/" "src/alembic/") ;;
  gateway*)    ALLOWED=("src/gateway/" "tests/gateway/" "src/shared/") ;;
  frontend*)   ALLOWED=("frontend/") ;;
  mcp*)        ALLOWED=("mcp-server/") ;;
  assign*)     ALLOWED=("src/gateway/" "src/board/" "tests/gateway/" "tests/board/") ;;
  e2e*)        ALLOWED=("tests/e2e/") ;;
  *)           exit 0 ;;
esac

REL_PATH="${FILE_PATH#$CWD/}"

for pattern in "${ALLOWED[@]}"; do
  [[ "$REL_PATH" == $pattern* ]] && exit 0
done

echo "Blocked: Branch '$BRANCH' can only write to: ${ALLOWED[*]}" >&2
echo "Attempted write to: $REL_PATH" >&2
exit 2
