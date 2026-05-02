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
# Routed through close-zellij-tab.sh which refuses to close the focused
# (supervisor) tab — see T-339. Exit 2 from the helper means "would have
# killed the supervisor"; surface it as a hard error instead of swallowing
# it like other failures, so the operator can re-focus and retry.
if [[ -n "${ZELLIJ:-}" ]]; then
  HELPER="$(dirname "$0")/lib/close-zellij-tab.sh"
  if [[ -x "$HELPER" ]]; then
    "$HELPER" "$WORKTREE_NAME"
    rc=$?
    if [[ $rc -eq 2 ]]; then
      echo "worktree-remove: close-zellij-tab refused (focused tab); leave the tab open and re-run after focusing elsewhere" >&2
      exit 2
    fi
  fi
fi

exit 0
