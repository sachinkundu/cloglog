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

# T-312: parse via shared stdlib helper, NEVER the python YAML lib.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/parse-yaml-scalar.sh
source "${HOOK_DIR}/lib/parse-yaml-scalar.sh"
BACKEND_URL=$(read_yaml_scalar "$CONFIG" "backend_url" "http://localhost:8000")
PROJECT_NAME=$(read_yaml_scalar "$CONFIG" "project" "")

# --- Resolve API key ---
# T-214: read from env or ~/.cloglog/credentials* only. Per-worktree files
# (.env, .mcp.json) MUST NOT carry the project key — anything inside the
# worktree is reachable by tooling that bypasses MCP.
# T-382: env → ~/.cloglog/credentials.d/<project_slug> → legacy global. On
# multi-project hosts the legacy-only path picked up another project's key
# and the registration POST was rejected, leaving the new worktree
# half-registered (board row missing) until the agent's first MCP call
# eventually wrote it.
# shellcheck source=lib/resolve-api-key.sh
source "${HOOK_DIR}/lib/resolve-api-key.sh"
API_KEY=$(resolve_api_key "$CONFIG")

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
# T-378: propagate the bootstrap script's exit status. The pre-T-378 `|| true`
# suppression masked silent partial setup on the WorktreeCreate path —
# .cloglog/on-worktree-create.sh now exits non-zero on missing credentials
# or any non-201 close-off-task response, and discarding that signal here
# would let the hook return success while the worktree shipped without a
# close-off task (the exact failure mode T-378 closes on the launch path).
if [[ -x "${CONFIG_DIR}/on-worktree-create.sh" ]]; then
  WORKTREE_PATH="$WORKTREE_PATH" WORKTREE_NAME="$WORKTREE_NAME" \
    "${CONFIG_DIR}/on-worktree-create.sh"
  _bootstrap_status=$?
  if [[ "$_bootstrap_status" -ne 0 ]]; then
    echo "[worktree-create] FATAL ${CONFIG_DIR}/on-worktree-create.sh exited ${_bootstrap_status}; worktree bootstrap incomplete." >&2
    exit "$_bootstrap_status"
  fi
fi

exit 0
