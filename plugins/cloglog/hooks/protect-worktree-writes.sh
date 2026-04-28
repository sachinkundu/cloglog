#!/bin/bash
# PreToolUse hook: enforce worktree discipline — agents can only write to assigned directories.
# Reads worktree_scopes from .cloglog/config.yaml via the stdlib-only parser at
# lib/parse-worktree-scopes.py (T-313 / Phase 0b — replaces the previous inline
# python+PyYAML block which silently failed on hosts without PyYAML).
# Detects worktree via git commands, not path patterns.

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# --- Detect if we're in a worktree ---
GIT_DIR=$(cd "$CWD" && git rev-parse --git-dir 2>/dev/null) || exit 0
GIT_COMMON=$(cd "$CWD" && git rev-parse --git-common-dir 2>/dev/null) || exit 0

# Normalize to absolute paths
GIT_DIR_ABS=$(cd "$CWD" && cd "$GIT_DIR" && pwd)
GIT_COMMON_ABS=$(cd "$CWD" && cd "$GIT_COMMON" && pwd)

# Not a worktree — allow all writes
[[ "$GIT_DIR_ABS" != "$GIT_COMMON_ABS" ]] || exit 0

# Get the worktree name from current directory basename
WORKTREE_NAME=$(basename "$CWD")
# Strip wt- prefix if present
SCOPE_NAME="${WORKTREE_NAME#wt-}"

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
[[ -n "$FILE_PATH" ]] || exit 0

# --- Find config ---
find_config() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.cloglog/config.yaml" ]]; then
      echo "$dir/.cloglog/config.yaml"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  # Check main repo root via git-common-dir
  local main_root
  main_root=$(dirname "$GIT_COMMON_ABS")
  if [[ -f "$main_root/.cloglog/config.yaml" ]]; then
    echo "$main_root/.cloglog/config.yaml"
    return 0
  fi
  return 1
}

CONFIG=$(find_config "$CWD") || {
  echo "Blocked: .cloglog/config.yaml not found — cannot enforce worktree scope" >&2
  exit 2
}

# --- Look up allowed directories for this worktree scope ---
# Supports prefix matching: "frontend-auth" matches "frontend" scope.
# The parser is stdlib-only — see lib/parse-worktree-scopes.py for the
# supported YAML subset and why we can't reach for PyYAML here.
#
# Fail closed on parser failure: a malformed config (mid-edit, merge
# conflict markers, unsupported YAML construct) must BLOCK writes, not
# silently allow them. The previous PyYAML-based snippet swallowed
# ImportError into allow-all; preserving that fallthrough here would
# defeat the whole point of T-313.
PARSER_STDERR=$(mktemp)
ALLOWED=$(python3 "${HOOK_DIR}/lib/parse-worktree-scopes.py" "$CONFIG" "$SCOPE_NAME" 2>"$PARSER_STDERR")
PARSER_RC=$?
if [[ $PARSER_RC -ne 0 ]]; then
  echo "Blocked: failed to parse worktree_scopes from $CONFIG (rc=$PARSER_RC)" >&2
  cat "$PARSER_STDERR" >&2
  rm -f "$PARSER_STDERR"
  exit 2
fi
rm -f "$PARSER_STDERR"

# Empty — no scope defined for this worktree, allow all writes.
if [[ -z "$ALLOWED" ]]; then
  exit 0
fi

# Make file path relative to CWD
REL_PATH="${FILE_PATH#$CWD/}"

# Check if file is in an allowed directory.
IFS=',' read -ra ALLOWED_ARR <<< "$ALLOWED"
for pattern in "${ALLOWED_ARR[@]}"; do
  if [[ "$REL_PATH" == "$pattern"* ]]; then
    exit 0
  fi
done

ALLOWED_DIRS="${ALLOWED//,/ }"
echo "Blocked: Worktree '$WORKTREE_NAME' can only write to: $ALLOWED_DIRS" >&2
echo "Attempted write to: $REL_PATH" >&2
exit 2
