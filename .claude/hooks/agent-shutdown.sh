#!/bin/bash
# SessionEnd hook: calls unregister and generates shutdown artifacts for worktree agents.
# Only runs if cwd is inside a worktree directory.
# IMPORTANT: Unregister runs FIRST (most critical), artifacts after.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Fast exit: not a worktree agent
[[ "$CWD" == *"/.claude/worktrees/"* ]] || exit 0

WORKTREE_NAME=$(echo "$CWD" | grep -oP '\.claude/worktrees/\K[^/]+')
ARTIFACTS_DIR="${CWD}/shutdown-artifacts"
mkdir -p "$ARTIFACTS_DIR"

# --- Resolve API key FIRST (fast) ---
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

# --- Generate minimal artifacts (fast file writes only) ---
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

# --- Call unregister-by-path (critical path) ---
if [[ -n "$API_KEY" ]]; then
  curl -s --max-time 5 -X POST "http://localhost:8000/api/v1/agents/unregister-by-path" \
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
