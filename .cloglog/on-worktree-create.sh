#!/bin/bash
# Project-specific worktree setup for cloglog.
# Called by the cloglog plugin's launch skill (or WorktreeCreate hook).
# Env: WORKTREE_PATH, WORKTREE_NAME (set by caller)

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="${REPO_ROOT}/scripts"

# Set up isolated infrastructure (ports, database, migrations, .env)
WORKTREE_PATH="$WORKTREE_PATH" WORKTREE_NAME="$WORKTREE_NAME" \
  "$SCRIPT_DIR/worktree-infra.sh" up

# Install Python dependencies (include dev toolchain: pytest, mypy, ruff, pytest-cov)
cd "$WORKTREE_PATH"
if [[ -f "pyproject.toml" ]]; then
  uv sync --extra dev || true
  [[ -x "$WORKTREE_PATH/.venv/bin/pytest" ]] || echo "WARN: pytest not in $WORKTREE_PATH/.venv — re-run 'uv sync --extra dev' manually"
fi

# Frontend deps (if worktree touches frontend)
if [[ "$WORKTREE_NAME" == wt-frontend* ]] && [[ -d "frontend" ]]; then
  cd frontend && npm install && cd ..
fi

# MCP server deps (if worktree touches mcp-server)
if [[ "$WORKTREE_NAME" == wt-mcp* ]] && [[ -d "mcp-server" ]]; then
  cd mcp-server && npm install && cd ..
fi
