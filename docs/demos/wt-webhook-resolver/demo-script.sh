#!/usr/bin/env bash
# Demo: T-254 — webhook resolver no longer crashes on issue_comment events
# whose head_branch is empty, and branch_name is now derived inside the
# agent-vm by cloglog-mcp (where the worktree path actually exists) rather
# than by the backend (which runs on the host and cannot see VM-local paths).
#
# Called by `make demo`. Relies on the worktree's isolated Postgres at
# $DATABASE_URL.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

set -a; source "$REPO_ROOT/.env"; set +a

# Normalize slashes to hyphens so a branch like `feat/foo` writes into
# `docs/demos/feat-foo/` — matching how scripts/check-demo.sh discovers the
# demo directory (it runs `${FEATURE//\//-}` on the branch name too).
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BRANCH_DIR="${BRANCH//\//-}"
DEMO_FILE="docs/demos/$BRANCH_DIR/demo.md"
PROBE="docs/demos/$BRANCH_DIR/probe.py"

uvx showboat init "$DEMO_FILE" \
  "GitHub issue_comment webhooks no longer crash the AgentNotifierConsumer, and cloglog-mcp (running inside the agent-vm) now derives branch_name at register time so the backend's resolver has the data it needs to route events."

# --- Background ------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Bug scenario: every issue_comment webhook arrives with an empty \
head_branch. Live-prod worktrees had branch_name='' (cloglog-mcp used to \
omit it on register), so the resolver's fallback ran WHERE branch_name='' \
AND status='online' and matched every live worktree at once → \
sqlalchemy.exc.MultipleResultsFound."

uvx showboat note "$DEMO_FILE" \
  "Architecture note (docs/ddd-context-map.md): cloglog runs on the host, \
cloglog-mcp runs inside each agent-vm. Worktree paths are VM-local. \
Branch derivation therefore belongs in the MCP server (which has filesystem \
access), not the backend. The backend is a pass-through that stores what \
the MCP sends."

# --- Proof 1: resolver short-circuits on empty head_branch ----------------

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — resolver guard. Seed three online worktrees that all carry the \
pre-fix empty branch_name, then hand _resolve_agent an issue_comment event \
whose head_branch=''. Before the fix this raised MultipleResultsFound; now \
it short-circuits and returns None."

uvx showboat exec "$DEMO_FILE" bash "DATABASE_URL=\"$DATABASE_URL\" uv run python $PROBE seed"
uvx showboat exec "$DEMO_FILE" bash "DATABASE_URL=\"$DATABASE_URL\" uv run python $PROBE resolve"

# --- Proof 2: repository defensive guard ----------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 2 — belt-and-suspenders. AgentRepository.get_worktree_by_branch \
itself refuses empty branch_name, so any future caller that forgets the \
upstream guard still cannot trigger the crash."

uvx showboat exec "$DEMO_FILE" bash "DATABASE_URL=\"$DATABASE_URL\" uv run python $PROBE repo"

# --- Proof 3: reconnect preserves populated branch_name -------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — reconnect never wipes a populated branch_name. If a transient \
MCP-side git probe fails and the next register arrives empty, \
upsert_worktree keeps the previously-stored name. Prevents regressions that \
would reopen the empty-branch data trap."

uvx showboat exec "$DEMO_FILE" bash "DATABASE_URL=\"$DATABASE_URL\" uv run python $PROBE reconnect"

# --- Proof 4: MCP-side derivation + wire payload --------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 4 — branch_name is derived inside cloglog-mcp. The TypeScript test \
'register_agent derives branch_name via git and POSTs both to \
/agents/register' init-s a real git repo, invokes register_agent, and \
asserts the request body includes the resolved branch. 54 tests, all pass."

uvx showboat exec "$DEMO_FILE" bash \
  "cd mcp-server && npx vitest run --reporter=json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f\"tests: {d[\"numPassedTests\"]} passed / {d[\"numTotalTests\"]} total\")'"

uvx showboat verify "$DEMO_FILE"
