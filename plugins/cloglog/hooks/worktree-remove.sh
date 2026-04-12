#!/bin/bash
# WorktreeRemove hook: fires when Claude Code removes a worktree.
# Runs project-specific teardown and closes zellij tab if applicable.

INPUT=$(cat)
WORKTREE_PATH=$(echo "$INPUT" | jq -r '.worktree_path // empty')

[[ -n "$WORKTREE_PATH" ]] || exit 0

WORKTREE_NAME=$(basename "$WORKTREE_PATH")

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
  # For removed worktrees, try the main repo root
  local repo_root
  repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || return 1
  if [[ -f "$repo_root/.cloglog/config.yaml" ]]; then
    echo "$repo_root/.cloglog/config.yaml"
    return 0
  fi
  return 1
}

CONFIG=$(find_config "$WORKTREE_PATH") || true
CONFIG_DIR=""
if [[ -n "$CONFIG" ]]; then
  CONFIG_DIR=$(dirname "$CONFIG")
fi

# --- Run project-specific teardown hook if it exists ---
if [[ -n "$CONFIG_DIR" ]] && [[ -x "${CONFIG_DIR}/on-worktree-destroy.sh" ]]; then
  WORKTREE_PATH="$WORKTREE_PATH" WORKTREE_NAME="$WORKTREE_NAME" \
    "${CONFIG_DIR}/on-worktree-destroy.sh" || true
fi

# --- Close zellij tab for the worktree (if running in zellij) ---
if command -v zellij &>/dev/null && [[ -n "$ZELLIJ" ]]; then
  TAB_ID=$(zellij action list-tabs 2>/dev/null | awk -v name="$WORKTREE_NAME" '$3 == name {print $1}')
  if [[ -n "$TAB_ID" ]]; then
    zellij action close-tab --tab-id "$TAB_ID" 2>/dev/null || true
  fi
fi

exit 0
