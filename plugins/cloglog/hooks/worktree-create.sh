#!/bin/bash
# WorktreeCreate hook: fires when Claude Code creates a native worktree.
# Registers agent on the board and runs project-specific setup.

INPUT=$(cat)
WORKTREE_PATH=$(echo "$INPUT" | jq -r '.worktree_path // empty')

[[ -n "$WORKTREE_PATH" ]] || exit 0

WORKTREE_NAME=$(basename "$WORKTREE_PATH")

# --- Find config (check main repo root, since worktree may not have .cloglog/) ---
find_config() {
  local dir="$1"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.cloglog/config.yaml" ]]; then
      echo "$dir/.cloglog/config.yaml"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  # Check main repo root via git
  local repo_root
  repo_root=$(cd "$1" && git rev-parse --show-toplevel 2>/dev/null) || return 1
  if [[ -f "$repo_root/.cloglog/config.yaml" ]]; then
    echo "$repo_root/.cloglog/config.yaml"
    return 0
  fi
  return 1
}

CONFIG=$(find_config "$WORKTREE_PATH") || exit 0
CONFIG_DIR=$(dirname "$CONFIG")

# Read backend_url and project from config
eval "$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$CONFIG'))
print('BACKEND_URL=' + repr(cfg.get('backend_url', 'http://localhost:8000')))
print('PROJECT_NAME=' + repr(cfg.get('project', '')))
" 2>/dev/null)" || exit 0

# --- Resolve API key ---
API_KEY="${CLOGLOG_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  API_KEY=$(grep CLOGLOG_API_KEY "${WORKTREE_PATH}/.env" 2>/dev/null | cut -d= -f2 || true)
fi
if [[ -z "$API_KEY" ]]; then
  REPO_ROOT=$(cd "$WORKTREE_PATH" && git rev-parse --show-toplevel 2>/dev/null || true)
  if [[ -n "$REPO_ROOT" ]] && [[ -f "${REPO_ROOT}/.mcp.json" ]]; then
    API_KEY=$(python3 -c "
import json
d=json.load(open('${REPO_ROOT}/.mcp.json'))
print(d.get('mcpServers',{}).get('cloglog',{}).get('env',{}).get('CLOGLOG_API_KEY',''))
" 2>/dev/null || true)
  fi
fi

# --- Register agent on the board ---
if [[ -n "$API_KEY" ]]; then
  BRANCH=$(cd "$WORKTREE_PATH" && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$WORKTREE_NAME")
  curl -s --max-time 5 -X POST "${BACKEND_URL}/api/v1/agents/register" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_name\": \"${WORKTREE_NAME}\",
      \"worktree_path\": \"${WORKTREE_PATH}\",
      \"branch\": \"${BRANCH}\"
    }" > /tmp/worktree-create-debug.log 2>&1 || true
fi

# --- Run project-specific setup hook if it exists ---
if [[ -x "${CONFIG_DIR}/on-worktree-create.sh" ]]; then
  WORKTREE_PATH="$WORKTREE_PATH" WORKTREE_NAME="$WORKTREE_NAME" \
    "${CONFIG_DIR}/on-worktree-create.sh" || true
fi

exit 0
