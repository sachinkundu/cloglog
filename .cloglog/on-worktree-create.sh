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

# T-257: MCP server deps — install whenever mcp-server/package.json exists
# on this worktree, regardless of WORKTREE_NAME. The previous guard fired
# only on wt-mcp* branches, so any other worktree that happened to touch
# mcp-server/ (e.g. T-244 wt-c2-mcp-rebuild) landed without node_modules
# and the very first `make quality` failed on `npx tsc` with "This is not
# the tsc command you are looking for" because the compiler was missing.
# The install is ~1-2 s with a warm cache; unconditional trigger trades
# that for zero foot-guns. The package.json guard lets downstream
# projects that use this plugin but have no mcp-server/ skip the install
# cleanly — we need the manifest for `npm install` to do anything useful
# anyway.
if [[ -f "mcp-server/package.json" ]]; then
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

# T-246: file a close-off task on the board so worktree teardown is visible
# work, not an ad-hoc main-agent chore. Hits the backend directly with the
# project API key — the same auth shape /agents/register uses — so the hook
# does not require an MCP session or the MCP service key. Backend is the
# source of truth for idempotency: re-running against the same worktree_path
# returns the existing task (HTTP 201, body.created=false).
#
# Non-fatal by design: if the backend is unreachable, the auth key is
# missing, or the worktree has not been registered yet, log and continue so
# worktree bootstrap does not wedge. The main agent can re-file the task
# after the fact via the MCP tool.
_resolve_api_key() {
  if [[ -n "${CLOGLOG_API_KEY:-}" ]]; then
    echo "$CLOGLOG_API_KEY"
    return
  fi
  local cred="${HOME}/.cloglog/credentials"
  if [[ -r "$cred" ]]; then
    local v
    v=$(grep '^CLOGLOG_API_KEY=' "$cred" 2>/dev/null | head -n 1 | cut -d= -f2-)
    [[ -n "$v" ]] && echo "$v"
  fi
}

_resolve_backend_url() {
  # T-259: parse backend_url with grep+sed, NEVER `python3 -c 'import yaml'`.
  # The system `python3` this hook runs under typically lacks pyyaml (the
  # project's pyyaml lives in the uv venv, not the global python). The
  # previous python snippet silently swallowed ImportError and returned the
  # `http://localhost:8000` default, so the subsequent close-off-task POST
  # landed on port 8000 even on hosts where the backend actually binds to
  # 127.0.0.1:8001 — the create succeeded from curl's view (HTTP 000 is
  # non-fatal-by-design, logged as WARN) but no task ever reached the
  # board. Authoritative precedent for this grep+sed pattern:
  # plugins/cloglog/hooks/agent-shutdown.sh:62-74. If you need another
  # config key here, extend this pattern; do NOT re-introduce `import yaml`.
  local cfg="${REPO_ROOT}/.cloglog/config.yaml"
  local default="http://localhost:8000"
  if [[ -f "$cfg" ]]; then
    local parsed
    parsed=$(grep '^backend_url:' "$cfg" | head -n1 \
             | sed 's/^backend_url:[[:space:]]*//' \
             | sed 's/[[:space:]]*#.*$//' \
             | tr -d '"'"'")
    if [[ -n "$parsed" ]]; then
      echo "$parsed"
      return
    fi
  fi
  echo "$default"
}

if [[ -n "${WORKTREE_PATH:-}" ]] && [[ -n "${WORKTREE_NAME:-}" ]]; then
  _api_key=$(_resolve_api_key)
  _backend_url=$(_resolve_backend_url)
  # T-259: log the resolved URL unconditionally so that a silent fall-back
  # to localhost:8000 on a host with a non-default backend port is visible
  # in bootstrap output instead of hiding behind a WARN status code.
  echo "[on-worktree-create] backend_url=${_backend_url}" >&2
  if [[ -z "$_api_key" ]]; then
    echo "[on-worktree-create] skipping close-off-task creation: no CLOGLOG_API_KEY available" >&2
  else
    _body=$(printf '{"worktree_path":"%s","worktree_name":"%s"}' \
      "${WORKTREE_PATH}" "${WORKTREE_NAME}")
    _resp=$(curl -sS --max-time 5 -o /tmp/cloglog-close-off-$$.out -w '%{http_code}' \
      -X POST "${_backend_url}/api/v1/agents/close-off-task" \
      -H 'Content-Type: application/json' \
      -H "Authorization: Bearer ${_api_key}" \
      -d "$_body" 2>/dev/null || echo "000")
    if [[ "$_resp" == "201" ]]; then
      echo "[on-worktree-create] close-off task filed for ${WORKTREE_NAME}"
    else
      echo "[on-worktree-create] WARN close-off task create returned HTTP ${_resp}; continuing" >&2
      if [[ -s /tmp/cloglog-close-off-$$.out ]]; then
        sed 's/^/[on-worktree-create]   /' /tmp/cloglog-close-off-$$.out >&2
      fi
    fi
    rm -f /tmp/cloglog-close-off-$$.out
  fi
fi
