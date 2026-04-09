#!/bin/bash
set -euo pipefail

# Create a worktree for a specific agent track with full setup.
# Usage: ./scripts/create-worktree.sh <worktree-name> [plan-file] [task-description]
#
# Examples:
#   ./scripts/create-worktree.sh wt-board
#   ./scripts/create-worktree.sh wt-board docs/superpowers/plans/2026-04-01-phase-1.md "Board context: models, CRUD, import, roll-up"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WORKTREE_NAME="${1:?Usage: $0 <worktree-name> [plan-file] [task-description]}"
PLAN_FILE="${2:-}"
TASK_DESC="${3:-}"

WORKTREE_DIR="${REPO_ROOT}/.claude/worktrees/${WORKTREE_NAME}"
BRANCH_NAME="${WORKTREE_NAME}"

# ── Worktree directory mapping ──────────────────────────────

declare -A ALLOWED_DIRS
ALLOWED_DIRS=(
  [wt-board]="src/board/, tests/board/, src/alembic/"
  [wt-agent]="src/agent/, tests/agent/, src/alembic/, mcp-server/"
  [wt-document]="src/document/, tests/document/, src/alembic/"
  [wt-gateway]="src/gateway/, tests/gateway/"
  [wt-gateway-sse]="src/gateway/sse.py, src/shared/events.py, tests/gateway/"
  [wt-frontend]="frontend/"
  [wt-frontend-live]="frontend/"
  [wt-frontend-docs]="frontend/"
  [wt-mcp]="mcp-server/"
  [wt-mcp-tools]="mcp-server/"
  [wt-mcp-docs]="mcp-server/"
  [wt-assign]="src/gateway/cli.py, src/board/routes.py, tests/gateway/, tests/board/"
  [wt-e2e]="tests/e2e/"
  [wt-claude-md]="docs/templates/"
  [wt-agent-vm]="(agent-vm repo)"
)

declare -A CONTEXT_NAMES
CONTEXT_NAMES=(
  [wt-board]="Board bounded context"
  [wt-agent]="Agent bounded context"
  [wt-document]="Document bounded context"
  [wt-gateway]="Gateway context"
  [wt-gateway-sse]="Gateway SSE + event bus"
  [wt-frontend]="React frontend"
  [wt-frontend-live]="React frontend — live dashboard"
  [wt-frontend-docs]="React frontend — document viewer"
  [wt-mcp]="MCP server"
  [wt-mcp-tools]="MCP server — agent tools"
  [wt-mcp-docs]="MCP server — document attachment"
  [wt-assign]="Task assignment (Gateway + Board)"
  [wt-e2e]="End-to-end tests"
  [wt-claude-md]="CLAUDE.md templates"
  [wt-agent-vm]="agent-vm integration"
)

declare -A TEST_COMMANDS
TEST_COMMANDS=(
  [wt-board]="make test-board"
  [wt-agent]="make test-agent"
  [wt-document]="make test-document"
  [wt-gateway]="make test-gateway"
  [wt-gateway-sse]="make test-gateway"
  [wt-frontend]="cd frontend && make test"
  [wt-frontend-live]="cd frontend && make test"
  [wt-frontend-docs]="cd frontend && make test"
  [wt-mcp]="cd mcp-server && make test"
  [wt-mcp-tools]="cd mcp-server && make test"
  [wt-mcp-docs]="cd mcp-server && make test"
  [wt-assign]="make test-gateway && make test-board"
  [wt-e2e]="make test-e2e"
)

DIRS="${ALLOWED_DIRS[$WORKTREE_NAME]:-unknown}"
CONTEXT="${CONTEXT_NAMES[$WORKTREE_NAME]:-$WORKTREE_NAME}"
TEST_CMD="${TEST_COMMANDS[$WORKTREE_NAME]:-make test}"

if [[ "$DIRS" == "unknown" ]]; then
  echo "Warning: unknown worktree name '$WORKTREE_NAME'. No directory restrictions will apply."
fi

# ── Create worktree ─────────────────────────────────────────

echo "Creating worktree: $WORKTREE_NAME"
echo "  Branch: $BRANCH_NAME"
echo "  Path:   $WORKTREE_DIR"
echo "  Context: $CONTEXT"
echo ""

if [[ -d "$WORKTREE_DIR" ]]; then
  echo "Worktree already exists at $WORKTREE_DIR"
  echo "Use: git worktree remove $WORKTREE_DIR  (to remove)"
  exit 1
fi

git worktree add -b "$BRANCH_NAME" "$WORKTREE_DIR" main
echo "Worktree created."

# Remove stale AGENT_PROMPT.md inherited from previous worktrees
# The launching agent will write a fresh prompt before starting the agent
if [[ -f "$WORKTREE_DIR/AGENT_PROMPT.md" ]]; then
  rm "$WORKTREE_DIR/AGENT_PROMPT.md"
  echo "  Removed stale AGENT_PROMPT.md (will be written by launcher)"
fi

# ── Install dependencies ────────────────────────────────────

echo ""
echo "Installing dependencies..."

# Python backend
if [[ -f "$WORKTREE_DIR/pyproject.toml" ]]; then
  echo "  Python: uv sync"
  (cd "$WORKTREE_DIR" && uv sync --all-extras --quiet)
fi

# Frontend
if [[ -d "$WORKTREE_DIR/frontend" ]]; then
  echo "  Frontend: npm install"
  (cd "$WORKTREE_DIR/frontend" && npm install --silent 2>/dev/null)
fi

# MCP server
if [[ -d "$WORKTREE_DIR/mcp-server" ]]; then
  echo "  MCP server: npm install"
  (cd "$WORKTREE_DIR/mcp-server" && npm install --silent 2>/dev/null)
fi

# Set up isolated infrastructure (ports + database)
echo "  Infrastructure: setting up isolated ports and database"
export WORKTREE_PATH="$WORKTREE_DIR"
"$SCRIPT_DIR/worktree-infra.sh" up 2>&1 | sed 's/^/    /'

echo "Dependencies installed."

# ── Contract setup ─────────────────────────────────────────

CONTRACTS_DIR="${REPO_ROOT}/docs/contracts"
CONTRACT_FLAG="${4:-}"  # Optional: explicit contract file path

if [[ -n "$CONTRACT_FLAG" ]]; then
  CONTRACT_FILE="$CONTRACT_FLAG"
elif ls "$CONTRACTS_DIR"/*.openapi.yaml 1>/dev/null 2>&1; then
  # Use the most recently modified contract
  CONTRACT_FILE="$(ls -t "$CONTRACTS_DIR"/*.openapi.yaml | head -1)"
else
  CONTRACT_FILE=""
fi

if [[ -n "$CONTRACT_FILE" ]]; then
  echo ""
  echo "Setting up API contract..."

  # Copy contract into worktree for easy reference (not for committing)
  cp "$CONTRACT_FILE" "$WORKTREE_DIR/CONTRACT.yaml"
  echo "CONTRACT.yaml" >> "$WORKTREE_DIR/.gitignore"
  echo "  Copied contract: $(basename "$CONTRACT_FILE") → CONTRACT.yaml (gitignored)"

  # Generate TypeScript types for frontend worktrees
  if [[ "$WORKTREE_NAME" == wt-frontend* ]]; then
    echo "  Generating TypeScript types from contract..."
    (cd "$WORKTREE_DIR" && "$REPO_ROOT/scripts/generate-contract-types.sh" "$WORKTREE_DIR/CONTRACT.yaml" "$WORKTREE_DIR/frontend/src/api")
    echo "  Generated: frontend/src/api/generated-types.ts"
  fi

  echo "Contract setup complete."
fi

# ── Generate worktree-specific CLAUDE.md ────────────────────

CLAUDE_MD="$WORKTREE_DIR/CLAUDE.md"

cat > "$CLAUDE_MD" << CLAUDE_EOF
# Worktree: ${WORKTREE_NAME}

## Identity

You are an autonomous agent working in worktree \`${WORKTREE_NAME}\`.
Your context is: **${CONTEXT}**.

## Rules

**You MUST only modify files in these directories:**
${DIRS}

Do NOT touch files outside these directories. The worktree protection hook will block you if you try.

## Your Task
CLAUDE_EOF

if [[ -n "$TASK_DESC" ]]; then
  echo "" >> "$CLAUDE_MD"
  echo "$TASK_DESC" >> "$CLAUDE_MD"
fi

if [[ -n "$PLAN_FILE" ]]; then
  cat >> "$CLAUDE_MD" << CLAUDE_EOF

## Plan

Read the implementation plan at \`${PLAN_FILE}\` and find the tasks assigned to \`${WORKTREE_NAME}\`.
Execute them in order. Each task has exact code, commands, and expected output.

## Workflow

1. Read the plan and find your tasks
2. For each task:
   a. Write the failing test first
   b. Run it to verify it fails
   c. Write the implementation
   d. Run tests: \`${TEST_CMD}\`
   e. Commit with a descriptive message
3. After all tasks: run \`make quality\` to verify everything passes
4. Push your branch and create a PR

CLAUDE_EOF
else
  cat >> "$CLAUDE_MD" << CLAUDE_EOF

Awaiting task assignment. When you receive instructions, work only within your assigned directories.

## Testing

Run your context tests with: \`${TEST_CMD}\`
Before any commit, run: \`make quality\`

CLAUDE_EOF
fi

# Add contract section to CLAUDE.md if a contract exists
if [[ -n "$CONTRACT_FILE" ]]; then
  if [[ "$WORKTREE_NAME" == wt-frontend* ]]; then
    cat >> "$CLAUDE_MD" << 'CONTRACT_EOF'

## API Contract

This wave has a strict API contract at `CONTRACT.yaml`.
Generated TypeScript types are at `frontend/src/api/generated-types.ts`.

**Rules:**
- Import ALL API response types from `../api/generated-types.ts` via the re-exports in `../api/types.ts`
- NEVER hand-write API response interfaces — they come from the OpenAPI contract
- If you need a field that doesn't exist in the generated types, STOP — the contract must be updated first, not worked around
- TypeScript compilation will fail if you use wrong field names or types
CONTRACT_EOF
  else
    cat >> "$CLAUDE_MD" << 'CONTRACT_EOF'

## API Contract

This wave has a strict API contract at `CONTRACT.yaml`.

**Rules:**
- All new/modified endpoints MUST match the contract exactly: path, method, field names, field types, enum values
- Pydantic response schemas must produce JSON that matches the contract's response schemas
- Run `make contract-check` before committing to verify compliance
- If you need to change the API shape, STOP — the contract must be updated first
CONTRACT_EOF
  fi
fi

cat >> "$CLAUDE_MD" << CLAUDE_EOF

## Demo

After implementation, write a \`demo-script.sh\` and run \`make demo\` to produce a proof-of-work \`demo.md\`.
See the Proof-of-Work Demos section in the root CLAUDE.md for details.

## Infrastructure

This worktree uses isolated infrastructure. Ports and DB are in \`.env\`.
Source \`scripts/worktree-ports.sh\` for port assignments in demo scripts.

CLAUDE_EOF

cat >> "$CLAUDE_MD" << CLAUDE_EOF
## Git

You are on branch \`${BRANCH_NAME}\`. Commit frequently with descriptive messages.

**CRITICAL: All pushes and PRs MUST use the GitHub App bot identity.**

When ready to push and create a PR:

\`\`\`bash
# Get a bot token
BOT_TOKEN=\$(uv run --with "PyJWT[crypto]" --with requests ~/.agent-vm/credentials/gh-app-token.py)

# Push as the bot
git remote set-url origin "https://x-access-token:\${BOT_TOKEN}@github.com/sachinkundu/cloglog.git"
git push -u origin HEAD

# Create PR as the bot
GH_TOKEN="\$BOT_TOKEN" gh pr create --title "feat: ..." --body "..."
\`\`\`

**Never push or create PRs as the user's personal identity.** All agent work must come from the bot.

## Quality Gate

Before completing work or creating a PR, run \`make quality\` and verify it passes.
This is enforced by a hook — commits will be blocked if quality fails.

## IMPORTANT: Read Agent Learnings

Before starting work, read the **Agent Learnings** section in the root CLAUDE.md.
It contains hard-won lessons from previous waves that you MUST follow.
These are not suggestions — they are requirements from PR reviews.
CLAUDE_EOF

echo ""
echo "Generated CLAUDE.md for ${WORKTREE_NAME}"

# ── Summary ─────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Worktree ready: ${WORKTREE_NAME}"
echo "  Path: ${WORKTREE_DIR}"
echo "  Branch: ${BRANCH_NAME}"
echo "  Context: ${CONTEXT}"
echo ""
echo "  To start working:"
echo "    cd ${WORKTREE_DIR} && claude"
echo ""
echo "  To remove when done:"
echo "    git worktree remove ${WORKTREE_DIR}"
echo "    git branch -D ${BRANCH_NAME}"
echo "═══════════════════════════════════════════════════"
