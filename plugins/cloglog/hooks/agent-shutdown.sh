#!/bin/bash
# SessionEnd hook: generates shutdown artifacts and unregisters worktree agents.
# Detects worktree via git (comparing --git-common-dir vs --git-dir).
# Reads backend_url from .cloglog/config.yaml.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# T-217: write an unconditional breadcrumb as the very first step so that
# post-incident investigators can tell whether Claude ran SessionEnd at all,
# even if a subsequent step errors out. Presence of this file answers the
# "did the hook fire?" question; absence means Claude never ran it.
{
  echo "[$(date -Iseconds)] agent-shutdown.sh fired"
  echo "  cwd=${CWD}"
  echo "  tool_input_keys=$(echo "$INPUT" | jq -r 'keys | join(",")' 2>/dev/null || echo '?')"
} >> /tmp/agent-shutdown-debug.log 2>&1 || true

# --- Detect if we're in a worktree ---
GIT_DIR=$(cd "$CWD" && git rev-parse --git-dir 2>/dev/null) || exit 0
GIT_COMMON=$(cd "$CWD" && git rev-parse --git-common-dir 2>/dev/null) || exit 0

# Normalize to absolute paths for comparison
GIT_DIR=$(cd "$CWD" && cd "$GIT_DIR" && pwd)
GIT_COMMON=$(cd "$CWD" && cd "$GIT_COMMON" && pwd)

# If git-dir == git-common-dir, this is the main repo, not a worktree
if [[ "$GIT_DIR" == "$GIT_COMMON" ]]; then
  # Main agent: clear the inbox on exit so next session starts clean
  INBOX="${CWD}/.cloglog/inbox"
  if [[ -f "$INBOX" ]]; then
    > "$INBOX"
  fi
  exit 0
fi

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
  # Read backend_url via a small grep+sed rather than python/yaml:
  # the system `python3` on many machines lacks `pyyaml` (the project's
  # pyyaml lives in the uv venv, not the global python the hook runs
  # under), so the previous python snippet silently returned the
  # default and the unregister POST went to the wrong port.
  parsed=$(grep '^backend_url:' "$CONFIG" | head -1 \
           | sed 's/^backend_url:[[:space:]]*//' \
           | sed 's/[[:space:]]*#.*$//' \
           | tr -d '"'"'")
  [[ -n "$parsed" ]] && BACKEND_URL="$parsed"
fi

# --- Resolve API key ---
# T-214: env or ~/.cloglog/credentials only. The project key MUST NOT live
# inside any per-worktree file.
API_KEY="${CLOGLOG_API_KEY:-}"
if [[ -z "$API_KEY" ]] && [[ -r "${HOME}/.cloglog/credentials" ]]; then
  API_KEY=$(grep -E '^CLOGLOG_API_KEY=' "${HOME}/.cloglog/credentials" 2>/dev/null | head -n1 | cut -d= -f2- | tr -d '"'"'" || true)
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
# NOTE: append to the debug log rather than overwriting — the top-of-script
# breadcrumb (T-217) must survive this call so we can tell the hook fired
# even if the POST fails or API_KEY is absent.
if [[ -n "$API_KEY" ]]; then
  echo "[$(date -Iseconds)] agent-shutdown.sh calling unregister-by-path backend=${BACKEND_URL}" >> /tmp/agent-shutdown-debug.log
  curl -s --max-time 5 -X POST "${BACKEND_URL}/api/v1/agents/unregister-by-path" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_path\": \"${CWD}\",
      \"artifacts\": {
        \"work_log\": \"${ARTIFACTS_DIR}/work-log.md\",
        \"learnings\": \"${ARTIFACTS_DIR}/learnings.md\"
      }
    }" >> /tmp/agent-shutdown-debug.log 2>&1 || true
else
  echo "[$(date -Iseconds)] agent-shutdown.sh: no API_KEY — skipping unregister-by-path (will rely on tier-3 heartbeat timeout)" >> /tmp/agent-shutdown-debug.log
fi

exit 0
