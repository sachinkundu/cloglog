#!/bin/bash
set -euo pipefail

# Clean up a wave of worktrees: kill agents, close zellij tab, remove worktrees + branches.
# Usage: ./scripts/cleanup-wave.sh <worktree-name> [worktree-name...]
#
# Examples:
#   ./scripts/cleanup-wave.sh wt-board wt-frontend wt-mcp
#   ./scripts/cleanup-wave.sh wt-gateway wt-agent wt-document

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <worktree-name> [worktree-name...]"
  echo ""
  echo "Current worktrees:"
  git worktree list
  exit 1
fi

WORKTREES=("$@")

echo "═══════════════════════════════════════════════════"
echo "  Cleaning up wave: ${WORKTREES[*]}"
echo "═══════════════════════════════════════════════════"
echo ""

# Step 1: Kill any Claude processes running in these worktrees
echo "── Step 1: Killing agent processes ──"
for wt in "${WORKTREES[@]}"; do
  WT_DIR="${REPO_ROOT}/.claude/worktrees/${wt}"
  # Find claude processes whose cwd is in the worktree directory
  PIDS=$(ps aux | grep "[c]laude.*dangerously" | grep "$wt" | awk '{print $2}' || true)
  if [[ -n "$PIDS" ]]; then
    echo "  Killing claude processes for $wt: $PIDS"
    echo "$PIDS" | xargs kill 2>/dev/null || true
  else
    # Also check by cwd
    for pid in $(pgrep -f "claude.*dangerously" 2>/dev/null || true); do
      CWD=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
      if [[ "$CWD" == *"$wt"* ]]; then
        echo "  Killing claude process $pid (cwd: $CWD)"
        kill "$pid" 2>/dev/null || true
      fi
    done
  fi
done
# Give processes time to exit
sleep 1
echo "  Done."
echo ""

# Step 2: Remove worktrees and branches
echo "── Step 2: Removing worktrees and branches ──"
for wt in "${WORKTREES[@]}"; do
  WT_DIR="${REPO_ROOT}/.claude/worktrees/${wt}"
  if [[ -d "$WT_DIR" ]]; then
    echo "  Removing $wt..."
    git worktree remove --force "$WT_DIR" 2>/dev/null || echo "    Warning: could not remove worktree $WT_DIR"
    git branch -D "$wt" 2>/dev/null && echo "    Deleted branch: $wt" || echo "    Branch $wt not found (may have been merged)"
  else
    echo "  Skipping $wt (not found at $WT_DIR)"
  fi
done
echo ""

# Step 3: Clean up remote branches if they've been merged
echo "── Step 3: Cleaning merged remote branches ──"
for wt in "${WORKTREES[@]}"; do
  # Check if the remote branch still exists
  if git ls-remote --heads origin "$wt" 2>/dev/null | grep -q "$wt"; then
    # Check if it's been merged to main
    MERGED=$(git branch -r --merged main 2>/dev/null | grep "origin/$wt" || true)
    if [[ -n "$MERGED" ]]; then
      echo "  Deleting merged remote branch: $wt"
      git push origin --delete "$wt" 2>/dev/null || echo "    Warning: could not delete remote branch $wt"
    else
      echo "  Remote branch $wt exists but is NOT merged — skipping"
    fi
  else
    echo "  Remote branch $wt already gone"
  fi
done
echo ""

# Step 4: Summary
echo "── Summary ──"
echo "  Remaining worktrees:"
git worktree list
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Wave cleanup complete."
echo "═══════════════════════════════════════════════════"
