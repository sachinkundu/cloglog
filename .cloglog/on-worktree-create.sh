#!/bin/bash
# Project-specific worktree setup for cloglog.
# Called by the cloglog plugin's launch skill (or WorktreeCreate hook).
# Env: WORKTREE_PATH, WORKTREE_NAME (set by caller)

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="${REPO_ROOT}/scripts"

# T-242: every worktree starts with a fresh shutdown-artifacts/ directory.
# Without this, newly created worktrees inherit stale work-log.md / learnings.md
# from whichever worktree seeded the template (originally wt-depgraph,
# 2026-04-05). Four downstream agents (T-247, T-249, T-253, devex-batch) had
# to overwrite before noticing the stale content. Agents generate these
# files from scratch during the shutdown sequence — no template seeding is
# required here; see docs/design/agent-lifecycle.md §2 step 4.
if [[ -n "${WORKTREE_PATH:-}" ]]; then
  rm -rf "${WORKTREE_PATH}/shutdown-artifacts"
  mkdir -p "${WORKTREE_PATH}/shutdown-artifacts"
fi

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

# T-214: warn if the project API key cannot be located.
# The MCP server reads CLOGLOG_API_KEY from env or ~/.cloglog/credentials only.
# Per-worktree files (.env, .mcp.json) must NOT carry the key.
if [[ -z "${CLOGLOG_API_KEY:-}" ]] && [[ ! -r "${HOME}/.cloglog/credentials" ]]; then
  echo "WARN: CLOGLOG_API_KEY not set and ${HOME}/.cloglog/credentials is missing." >&2
  echo "      The MCP server in this worktree will fail to authenticate." >&2
  echo "      See docs/setup-credentials.md for setup instructions." >&2
fi
