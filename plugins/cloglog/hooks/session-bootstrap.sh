#!/usr/bin/env bash
# SessionStart hook — prints a reminder for the human to run the setup skill.

# Only run for the main worktree (not worktree agents)
WORKTREE_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [[ "$WORKTREE_BRANCH" == wt-* ]]; then
  exit 0
fi

# Create inbox file if needed
PROJECT_DIR=$(pwd)
mkdir -p "${PROJECT_DIR}/.cloglog"
touch "${PROJECT_DIR}/.cloglog/inbox"

echo "Run /cloglog setup to register and start inbox monitor."
