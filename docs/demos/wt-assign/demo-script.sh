#!/bin/bash
# Demo: cloglog agents list CLI command
# Shows the new `agents list` command with table and JSON output.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

source scripts/worktree-ports.sh

echo "=== Demo: cloglog agents list ==="
echo ""
echo "--- 1. Show CLI help for agents list ---"
uv run python -m src.gateway.cli agents list --help
echo ""

echo "--- 2. Show agents list (table output) ---"
echo "Note: requires running server. Demonstrating via unit tests instead."
echo ""

echo "--- 3. Test results proving the command works ---"
uv run pytest tests/gateway/test_cli.py -v -k "agents" 2>&1
echo ""

echo "=== Demo complete ==="
