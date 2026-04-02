#!/bin/bash
set -euo pipefail

# Remove a worktree and its branch.
# Usage: ./scripts/remove-worktree.sh <worktree-name>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

FORCE=0
if [[ "${1:-}" == "--force" ]] || [[ "${1:-}" == "-f" ]]; then
  FORCE=1
  shift
fi

WORKTREE_NAME="${1:?Usage: $0 [-f|--force] <worktree-name>}"
WORKTREE_DIR="${REPO_ROOT}/.claude/worktrees/${WORKTREE_NAME}"
BRANCH_NAME="${WORKTREE_NAME}"

if [[ ! -d "$WORKTREE_DIR" ]]; then
  echo "Worktree not found: $WORKTREE_DIR"
  exit 1
fi

# Check for uncommitted changes
CHANGES=$(cd "$WORKTREE_DIR" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
if [[ "$CHANGES" -gt 0 ]] && [[ "$FORCE" -eq 0 ]]; then
  echo "Warning: $WORKTREE_NAME has $CHANGES uncommitted changes."
  read -p "Remove anyway? (y/N) " -r
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo "Removing worktree: $WORKTREE_NAME"
git worktree remove --force "$WORKTREE_DIR"
git branch -D "$BRANCH_NAME" 2>/dev/null && echo "Deleted branch: $BRANCH_NAME" || echo "Branch $BRANCH_NAME not found (may have been merged)"

echo "Done."
