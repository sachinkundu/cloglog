#!/usr/bin/env bash
# Demo: T-214 — agent worktrees no longer ship the project API key in plaintext.
# Called by `make demo` after the worktree backend is up.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# Make sure mcp-server/dist is current — `dist/` is gitignored.
( cd mcp-server && npx tsc >/dev/null )

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"

uvx showboat init "$DEMO_FILE" \
  "Operators can now run cloglog agents in worktrees without the project API key being readable inside the worktree."

# ─────────────────────────────────────────────────────────────────────────────
# 1. The committed .mcp.json no longer carries the key.
# ─────────────────────────────────────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "Before T-214, .mcp.json carried CLOGLOG_API_KEY in plaintext under mcpServers.cloglog.env. Any process inside the worktree could read it and authenticate to the backend with curl, bypassing the 'agents talk to the backend only via MCP' rule."

uvx showboat note "$DEMO_FILE" \
  "After T-214, the env block contains only CLOGLOG_URL. There is no project credential anywhere in the worktree."

uvx showboat exec "$DEMO_FILE" bash \
  'jq ".mcpServers.cloglog.env" .mcp.json'

uvx showboat exec "$DEMO_FILE" bash \
  'jq -r ".mcpServers.cloglog.env | keys[]" .mcp.json | sort'

# ─────────────────────────────────────────────────────────────────────────────
# 2. The key now lives at ~/.cloglog/credentials with 0600 perms, outside any worktree.
# ─────────────────────────────────────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "The MCP server reads CLOGLOG_API_KEY from the operator environment first, then from ~/.cloglog/credentials (mode 0600). The path is in the operator's home directory; agent-vm sandboxes never see it."

uvx showboat exec "$DEMO_FILE" bash \
  'stat -c "%a" "$HOME/.cloglog/credentials"'

uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "^CLOGLOG_API_KEY=" "$HOME/.cloglog/credentials"'

# ─────────────────────────────────────────────────────────────────────────────
# 3. Positive path — MCP server starts and reports ready when credentials resolve.
# ─────────────────────────────────────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "Positive path: the MCP server resolves the key (env or credentials file), connects its stdio transport, and prints its ready line. Stdin from /dev/null closes the transport, so the process exits cleanly with status 0."

uvx showboat exec "$DEMO_FILE" bash \
  'timeout 3 node mcp-server/dist/index.js < /dev/null 2>&1 | head -1; echo "exit=${PIPESTATUS[0]}"'

# ─────────────────────────────────────────────────────────────────────────────
# 4. Negative path — no env, no credentials file → loud failure with EX_CONFIG (78).
# ─────────────────────────────────────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "Negative path: with HOME pointed at a nonexistent directory and CLOGLOG_API_KEY unset, the MCP server prints an actionable diagnostic to stderr and exits with EX_CONFIG (78). Claude Code's MCP loader will surface this as a failed server — agents inside the worktree see no mcp__cloglog__* tools, so they cannot proceed without the operator fixing the credentials."

uvx showboat exec "$DEMO_FILE" bash \
  'HOME=/nonexistent env -u CLOGLOG_API_KEY node mcp-server/dist/index.js < /dev/null > /tmp/t214-neg.out 2>&1; ec=$?; cat /tmp/t214-neg.out; echo "exit=$ec"'

# ─────────────────────────────────────────────────────────────────────────────
# 5. Regression guard — automated test asserts .mcp.json never reintroduces the key.
# ─────────────────────────────────────────────────────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "A pytest regression guard (tests/test_mcp_json_no_secret.py) fails fast if anyone re-adds CLOGLOG_API_KEY (or a 64-hex token) to .mcp.json. It runs as part of make quality."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/test_mcp_json_no_secret.py -q 2>&1 | grep -oE "[0-9]+ passed" | head -1'

uvx showboat verify "$DEMO_FILE"
