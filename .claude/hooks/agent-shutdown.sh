#!/bin/bash
# SessionEnd hook: generates shutdown artifacts and calls unregister for worktree agents.
# Only runs if cwd is inside a worktree directory.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Fast exit: not a worktree agent
[[ "$CWD" == *"/.claude/worktrees/"* ]] || exit 0

WORKTREE_NAME=$(echo "$CWD" | grep -oP '\.claude/worktrees/\K[^/]+')
ARTIFACTS_DIR="${CWD}/shutdown-artifacts"
mkdir -p "$ARTIFACTS_DIR"

# --- Generate work log ---
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
  echo ""
  echo "## Pull Requests"
  BRANCH=$(cd "$CWD" && git branch --show-current 2>/dev/null)
  if [[ -n "$BRANCH" ]]; then
    gh pr list --head "$BRANCH" --json number,title,state,url 2>/dev/null || echo "[]"
  fi
} > "${ARTIFACTS_DIR}/work-log.md"

# --- Generate learnings template ---
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
API_KEY="${CLOGLOG_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  API_KEY=$(grep CLOGLOG_API_KEY "${CWD}/.env" 2>/dev/null | cut -d= -f2 || true)
fi

if [[ -n "$API_KEY" ]]; then
  curl -s -X POST "http://localhost:8000/api/v1/agents/unregister-by-path" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_path\": \"${CWD}\",
      \"artifacts\": {
        \"work_log\": \"${ARTIFACTS_DIR}/work-log.md\",
        \"learnings\": \"${ARTIFACTS_DIR}/learnings.md\"
      }
    }" 2>/dev/null || true
fi

exit 0
