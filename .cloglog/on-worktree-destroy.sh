#!/bin/bash
# Project-specific worktree cleanup for cloglog.
# Called by the cloglog plugin's close-wave skill (or WorktreeRemove hook).
# Env: WORKTREE_PATH, WORKTREE_NAME (set by caller)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="${REPO_ROOT}/scripts"

# Tear down isolated infrastructure (kill ports, drop DB, remove .env)
WORKTREE_PATH="$WORKTREE_PATH" WORKTREE_NAME="$WORKTREE_NAME" \
  "$SCRIPT_DIR/worktree-infra.sh" down 2>/dev/null || true
