#!/bin/bash
set -euo pipefail

# List all active cloglog worktrees with their status.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "═══ Active Worktrees ═══"
echo ""

git worktree list --porcelain | while read -r line; do
  if [[ "$line" == worktree\ * ]]; then
    path="${line#worktree }"
    # Skip the main worktree
    if [[ "$path" == "$REPO_ROOT" ]]; then
      continue
    fi
    name=$(basename "$path")
  elif [[ "$line" == branch\ * ]]; then
    branch="${line#branch refs/heads/}"
  elif [[ -z "$line" ]]; then
    if [[ -n "${name:-}" ]] && [[ "$name" != "$(basename "$REPO_ROOT")" ]]; then
      # Count uncommitted changes
      changes=$(cd "$path" && git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
      # Count commits ahead of main
      ahead=$(cd "$path" && git rev-list main..HEAD --count 2>/dev/null || echo "?")

      printf "  %-20s  branch: %-25s  commits: %s  uncommitted: %s\n" "$name" "$branch" "$ahead" "$changes"
    fi
    name=""
    branch=""
  fi
done

echo ""
