#!/bin/bash
set -euo pipefail

# Consolidated worktree management script.
# Replaces: remove-worktree.sh, cleanup-wave.sh, close-wave.sh
#
# Usage:
#   ./scripts/manage-worktrees.sh remove <worktree-name> [worktree-name...]
#   ./scripts/manage-worktrees.sh close <wave-name> <worktree-name> [worktree-name...]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="${1:?Usage: $0 <remove|close> [wave-name] <worktree-name> [worktree-name...]}"
shift

if [[ "$MODE" == "close" ]]; then
  WAVE_NAME="${1:?Usage: $0 close <wave-name> <worktree-name> [worktree-name...]}"
  shift
fi

WORKTREES=("$@")
if [[ ${#WORKTREES[@]} -eq 0 ]]; then
  echo "Error: provide at least one worktree name"
  exit 1
fi

echo "═══════════════════════════════════════════════════"
echo "  Mode: ${MODE}"
[[ "$MODE" == "close" ]] && echo "  Wave: ${WAVE_NAME}"
echo "  Worktrees: ${WORKTREES[*]}"
echo "═══════════════════════════════════════════════════"
echo ""

# --- Close mode: generate wave work log ---
if [[ "$MODE" == "close" ]]; then
  DATE=$(date +%Y-%m-%d)
  LOG_FILE="${REPO_ROOT}/docs/superpowers/work-logs/${DATE}-${WAVE_NAME}.md"
  mkdir -p "$(dirname "$LOG_FILE")"

  echo "── Generating wave work log ──"
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
        COMMITS=$(cd "$WT_DIR" && git log --oneline main..HEAD 2>/dev/null || echo "  (no commits)")
        echo "**Commits:**"
        echo '```'
        echo "$COMMITS"
        echo '```'
        echo ""

        FILES=$(cd "$WT_DIR" && git diff --name-only main..HEAD 2>/dev/null || echo "  (none)")
        echo "**Files changed:**"
        echo '```'
        echo "$FILES"
        echo '```'
      else
        echo "(worktree not found — may have been cleaned already)"
      fi

      PR_INFO=$(gh pr list --repo sachinkundu/cloglog --state merged --head "$wt" --json number,title,url --limit 1 2>/dev/null || echo "[]")
      PR_NUM=$(echo "$PR_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['number'] if d else 'N/A')" 2>/dev/null || echo "N/A")
      PR_TITLE=$(echo "$PR_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['title'] if d else 'N/A')" 2>/dev/null || echo "N/A")

      echo ""
      echo "**PR:** #${PR_NUM} — ${PR_TITLE}"
      echo ""
      echo "---"
      echo ""
    done
  } > "$LOG_FILE"
  echo "  Written to: $LOG_FILE"
  echo ""
fi

# --- Remove worktrees ---
echo "── Removing worktrees ──"
for wt in "${WORKTREES[@]}"; do
  WT_DIR="${REPO_ROOT}/.claude/worktrees/${wt}"
  if [[ -d "$WT_DIR" ]]; then
    echo "  Removing $wt..."
    git worktree remove --force "$WT_DIR" 2>/dev/null || echo "    Warning: could not remove $WT_DIR"
    git branch -D "$wt" 2>/dev/null && echo "    Deleted branch $wt" || echo "    Branch $wt not found"
  else
    echo "  Skipping $wt (not found at $WT_DIR)"
  fi
done
echo ""

# --- Clean remote branches ---
echo "── Cleaning remote branches ──"
for wt in "${WORKTREES[@]}"; do
  if git ls-remote --heads origin "$wt" 2>/dev/null | grep -q "$wt"; then
    MERGED=$(git branch -r --merged main 2>/dev/null | grep "origin/$wt" || true)
    if [[ -n "$MERGED" ]]; then
      echo "  Deleting merged remote branch: $wt"
      git push origin --delete "$wt" 2>/dev/null || echo "    Warning: could not delete"
    else
      echo "  Remote $wt exists but NOT merged — skipping"
    fi
  else
    echo "  Remote $wt already gone"
  fi
done
echo ""

# --- Close mode: update main ---
if [[ "$MODE" == "close" ]]; then
  echo "── Updating main ──"
  git checkout main 2>/dev/null || true
  git pull origin main 2>/dev/null || true
  echo ""
fi

# --- Summary ---
echo "═══════════════════════════════════════════════════"
echo "  Done."
if [[ "$MODE" == "close" ]]; then
  echo "  Wave work log: ${LOG_FILE}"
  echo "  Next: review work log, update CLAUDE.md learnings, commit"
fi
echo "  Remaining worktrees:"
git worktree list
echo "═══════════════════════════════════════════════════"
