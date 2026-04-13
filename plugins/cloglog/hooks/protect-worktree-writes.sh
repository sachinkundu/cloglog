#!/bin/bash
# PreToolUse hook: enforce worktree discipline — agents can only write to assigned directories.
# Reads worktree_scopes from .cloglog/config.yaml instead of hardcoded case statement.
# Detects worktree via git commands, not path patterns.

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

CONFIG=$(find_config "$CWD") || exit 0

# --- Look up allowed directories for this worktree scope ---
# Supports prefix matching: "frontend-auth" matches "frontend" scope
ALLOWED=$(CONFIG_PATH="$CONFIG" SCOPE_KEY="$SCOPE_NAME" python3 -c "
import yaml, sys, json, os

cfg = yaml.safe_load(open(os.environ['CONFIG_PATH']))
scopes = cfg.get('worktree_scopes', {})
scope_name = os.environ['SCOPE_KEY']

# Exact match first
if scope_name in scopes:
    print(json.dumps(scopes[scope_name]))
    sys.exit(0)

# Prefix match: 'frontend-auth' matches 'frontend'
for key in sorted(scopes.keys(), key=len, reverse=True):
    if scope_name.startswith(key):
        print(json.dumps(scopes[key]))
        sys.exit(0)

# No scope defined — allow all writes
print('[]')
" 2>/dev/null) || exit 0

# Empty or no scopes — allow all writes
if [[ "$ALLOWED" == "[]" ]] || [[ -z "$ALLOWED" ]]; then
  exit 0
fi

# Make file path relative to CWD
REL_PATH="${FILE_PATH#$CWD/}"

# Check if file is in an allowed directory
ALLOWED_JSON="$ALLOWED" REL_PATH_VAL="$REL_PATH" python3 -c "
import json, sys, os
allowed = json.loads(os.environ['ALLOWED_JSON'])
rel_path = os.environ['REL_PATH_VAL']
for pattern in allowed:
    if rel_path.startswith(pattern):
        sys.exit(0)
sys.exit(1)
" 2>/dev/null

if [[ $? -eq 0 ]]; then
  exit 0
fi

# Format allowed dirs for error message
ALLOWED_DIRS=$(ALLOWED_JSON="$ALLOWED" python3 -c "
import json, os
dirs = json.loads(os.environ['ALLOWED_JSON'])
print(' '.join(dirs))
" 2>/dev/null)

echo "Blocked: Worktree '$WORKTREE_NAME' can only write to: $ALLOWED_DIRS" >&2
echo "Attempted write to: $REL_PATH" >&2
exit 2
