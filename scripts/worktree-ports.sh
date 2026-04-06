#!/bin/bash
# Derives deterministic port assignments for the current worktree.
# Source this script to set BACKEND_PORT, FRONTEND_PORT, DB_PORT, WORKTREE_DB_NAME, DATABASE_URL.
#
# Usage:
#   export WORKTREE_PATH=/path/to/worktree  # optional, defaults to git toplevel
#   source scripts/worktree-ports.sh

set -euo pipefail

WORKTREE_PATH="${WORKTREE_PATH:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
WORKTREE_NAME=$(basename "$WORKTREE_PATH")

# Hash worktree name to a base port in range 10000-60000
BASE_PORT=$(( ($(echo "$WORKTREE_NAME" | cksum | cut -d' ' -f1) % 50000) + 10000 ))

export BACKEND_PORT=$BASE_PORT
export FRONTEND_PORT=$((BASE_PORT + 1))
export DB_PORT=$((BASE_PORT + 2))
export WORKTREE_DB_NAME="cloglog_${WORKTREE_NAME//-/_}"
export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/${WORKTREE_DB_NAME}"
