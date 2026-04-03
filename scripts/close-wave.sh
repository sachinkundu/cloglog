#!/bin/bash
set -euo pipefail

# Close a wave: generate work log, kill agents, clean worktrees, update main.
# Usage: ./scripts/close-wave.sh <wave-name> <worktree-name> [worktree-name...]
#
# Examples:
#   ./scripts/close-wave.sh "phase-1-wave-1" wt-board wt-frontend wt-mcp
#   ./scripts/close-wave.sh "phase-1-wave-2" wt-gateway wt-agent wt-document

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WAVE_NAME="${1:?Usage: $0 <wave-name> <worktree-name> [worktree-name...]}"
shift
WORKTREES=("$@")

if [[ ${#WORKTREES[@]} -eq 0 ]]; then
  echo "Error: provide at least one worktree name"
  exit 1
fi

DATE=$(date +%Y-%m-%d)
LOG_FILE="${REPO_ROOT}/docs/superpowers/work-logs/${DATE}-${WAVE_NAME}.md"

echo "═══════════════════════════════════════════════════"
echo "  Closing wave: ${WAVE_NAME}"
echo "  Worktrees: ${WORKTREES[*]}"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Step 1: Generate work log ──────────────────────────────

echo "── Step 1: Generating work log ──"
mkdir -p "$(dirname "$LOG_FILE")"

{
  echo "# Work Log: ${WAVE_NAME}"
  echo ""
  echo "**Date:** ${DATE}"
  echo "**Worktrees:** ${WORKTREES[*]}"
  echo ""
  echo "## Summary of Work"
  echo ""

  for wt in "${WORKTREES[@]}"; do
    WT_DIR="${REPO_ROOT}/.claude/worktrees/${wt}"
    echo "### ${wt}"
    echo ""

    if [[ -d "$WT_DIR" ]]; then
      # Get commit log for this branch
      COMMITS=$(cd "$WT_DIR" && git log --oneline main..HEAD 2>/dev/null || echo "  (no commits)")
      echo "**Commits:**"
      echo '```'
      echo "$COMMITS"
      echo '```'
      echo ""

      # Get files changed
      FILES=$(cd "$WT_DIR" && git diff --name-only main..HEAD 2>/dev/null || echo "  (none)")
      echo "**Files changed:**"
      echo '```'
      echo "$FILES"
      echo '```'
    else
      echo "(worktree not found — may have been cleaned already)"
    fi

    # Find the merged PR for this branch
    PR_INFO=$(gh pr list --repo sachinkundu/cloglog --state merged --head "$wt" --json number,title,mergedAt,url --limit 1 2>/dev/null || echo "[]")
    PR_NUM=$(echo "$PR_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['number'] if d else 'N/A')" 2>/dev/null || echo "N/A")
    PR_TITLE=$(echo "$PR_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['title'] if d else 'N/A')" 2>/dev/null || echo "N/A")

    echo ""
    echo "**PR:** #${PR_NUM} — ${PR_TITLE}"
    echo ""
    echo "---"
    echo ""
  done

  echo "## Learnings & Issues"
  echo ""
  echo "<!-- Fill in after reviewing the wave's PR feedback -->"
  echo "<!-- These should be distilled into CLAUDE.md Agent Learnings section -->"
  echo ""
  echo "## State After This Wave"
  echo ""
  echo "<!-- Brief description of what's now implemented and working -->"

} > "$LOG_FILE"

echo "  Work log written to: $LOG_FILE"
echo ""

# ── Step 2: Kill agent processes ───────────────────────────

echo "── Step 2: Killing agent processes ──"
for wt in "${WORKTREES[@]}"; do
  # Find by worktree name in command line
  PIDS=$(pgrep -f "claude.*${wt}" 2>/dev/null || true)
  if [[ -n "$PIDS" ]]; then
    echo "  Killing agents for $wt: $PIDS"
    echo "$PIDS" | xargs kill 2>/dev/null || true
  fi

  # Also find by cwd
  for pid in $(pgrep -f "claude.*dangerously" 2>/dev/null || true); do
    CWD=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
    if [[ "$CWD" == *"worktrees/${wt}"* ]]; then
      echo "  Killing agent $pid (cwd in $wt)"
      kill "$pid" 2>/dev/null || true
    fi
  done
done
sleep 2
echo "  Done."
echo ""

# ── Step 3: Remove worktrees and local branches ───────────

echo "── Step 3: Removing worktrees ──"
for wt in "${WORKTREES[@]}"; do
  WT_DIR="${REPO_ROOT}/.claude/worktrees/${wt}"
  if [[ -d "$WT_DIR" ]]; then
    echo "  Removing $wt..."
    git worktree remove --force "$WT_DIR" 2>/dev/null || echo "    Warning: could not remove $WT_DIR"
    git branch -D "$wt" 2>/dev/null && echo "    Deleted branch $wt" || echo "    Branch $wt already gone"
  else
    echo "  $wt already removed"
  fi
done
echo ""

# ── Step 4: Clean remote branches ─────────────────────────

echo "── Step 4: Cleaning remote branches ──"
git fetch --prune origin 2>/dev/null || true
for wt in "${WORKTREES[@]}"; do
  if git ls-remote --heads origin "$wt" 2>/dev/null | grep -q "$wt"; then
    echo "  Deleting remote branch: $wt"
    git push origin --delete "$wt" 2>/dev/null || echo "    Warning: could not delete"
  else
    echo "  Remote $wt already gone"
  fi
done
echo ""

# ── Step 5: Update main ───────────────────────────────────

echo "── Step 5: Updating main ──"
git checkout main 2>/dev/null || true
git pull origin main 2>/dev/null || true
echo ""

# ── Summary ────────────────────────────────────────────────

echo "═══════════════════════════════════════════════════"
echo "  Wave ${WAVE_NAME} closed."
echo ""
echo "  Work log: ${LOG_FILE}"
echo "  Next steps:"
echo "    1. Review and complete the work log"
echo "    2. Add learnings to CLAUDE.md Agent Learnings section"
echo "    3. Commit the work log and CLAUDE.md updates"
echo "    4. Launch next wave"
echo "═══════════════════════════════════════════════════"
