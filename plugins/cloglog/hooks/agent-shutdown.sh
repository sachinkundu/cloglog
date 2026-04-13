#!/bin/bash
# SessionEnd hook: generates shutdown artifacts and unregisters worktree agents.
# Detects worktree via git (comparing --git-common-dir vs --git-dir).
# Reads backend_url from .cloglog/config.yaml.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# --- Detect if we're in a worktree ---
GIT_DIR=$(cd "$CWD" && git rev-parse --git-dir 2>/dev/null) || exit 0
GIT_COMMON=$(cd "$CWD" && git rev-parse --git-common-dir 2>/dev/null) || exit 0

# Normalize to absolute paths for comparison
GIT_DIR=$(cd "$CWD" && cd "$GIT_DIR" && pwd)
GIT_COMMON=$(cd "$CWD" && cd "$GIT_COMMON" && pwd)

# If git-dir == git-common-dir, this is the main repo, not a worktree
[[ "$GIT_DIR" != "$GIT_COMMON" ]] || exit 0

WORKTREE_NAME=$(basename "$CWD")
ARTIFACTS_DIR="${CWD}/shutdown-artifacts"
mkdir -p "$ARTIFACTS_DIR"

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
  local repo_root
  repo_root=$(cd "$1" && git rev-parse --show-toplevel 2>/dev/null) || return 1
  if [[ -f "$repo_root/.cloglog/config.yaml" ]]; then
    echo "$repo_root/.cloglog/config.yaml"
    return 0
  fi
  return 1
}

CONFIG=$(find_config "$CWD") || true

BACKEND_URL="http://localhost:8000"
if [[ -n "$CONFIG" ]]; then
  BACKEND_URL=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$CONFIG'))
print(cfg.get('backend_url', 'http://localhost:8000'))
" 2>/dev/null) || BACKEND_URL="http://localhost:8000"
fi

# --- Resolve API key ---
API_KEY="${CLOGLOG_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  API_KEY=$(grep CLOGLOG_API_KEY "${CWD}/.env" 2>/dev/null | cut -d= -f2 || true)
fi
if [[ -z "$API_KEY" ]]; then
  REPO_ROOT=$(cd "$CWD" && git rev-parse --show-toplevel 2>/dev/null || true)
  if [[ -n "$REPO_ROOT" ]] && [[ -f "${REPO_ROOT}/.mcp.json" ]]; then
    API_KEY=$(python3 -c "
import json
d=json.load(open('${REPO_ROOT}/.mcp.json'))
print(d.get('mcpServers',{}).get('cloglog',{}).get('env',{}).get('CLOGLOG_API_KEY',''))
" 2>/dev/null || true)
  fi
fi

# --- Generate shutdown artifacts ---
{
  echo "# Work Log: ${WORKTREE_NAME}"
  echo ""
  echo "**Date:** $(date +%Y-%m-%d)"
  echo "**Worktree:** ${WORKTREE_NAME}"
  echo ""
  echo "## Commits"
  echo '```'
  cd "$CWD" && git log --oneline main..HEAD 2>/dev/null || echo "(no commits)"
  echo '```'
  echo ""
  echo "## Files Changed"
  echo '```'
  cd "$CWD" && git diff --name-only main..HEAD 2>/dev/null || echo "(none)"
  echo '```'
} > "${ARTIFACTS_DIR}/work-log.md"

{
  echo "# Learnings: ${WORKTREE_NAME}"
  echo ""
  echo "**Date:** $(date +%Y-%m-%d)"
  echo ""
  echo "## What Went Well"
  echo ""
  echo "<!-- Fill in during consolidation -->"
  echo ""
  echo "## Issues Encountered"
  echo ""
  echo "<!-- Fill in during consolidation -->"
  echo ""
  echo "## Suggestions for CLAUDE.md"
  echo ""
  echo "<!-- Fill in during consolidation -->"
} > "${ARTIFACTS_DIR}/learnings.md"

# --- Call unregister-by-path ---
if [[ -n "$API_KEY" ]]; then
  curl -s --max-time 5 -X POST "${BACKEND_URL}/api/v1/agents/unregister-by-path" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_path\": \"${CWD}\",
      \"artifacts\": {
        \"work_log\": \"${ARTIFACTS_DIR}/work-log.md\",
        \"learnings\": \"${ARTIFACTS_DIR}/learnings.md\"
      }
    }" > /tmp/agent-shutdown-debug.log 2>&1 || true
fi

exit 0
