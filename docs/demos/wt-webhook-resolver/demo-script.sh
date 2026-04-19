#!/usr/bin/env bash
# Demo: T-254 — webhook resolver no longer crashes on issue_comment events
# whose head_branch is empty, and every newly-registered worktree has its
# branch_name populated.
#
# Called by `make demo`. Relies on:
#   - the worktree's isolated Postgres at $DATABASE_URL
#   - the main `cloglog` DB for the live-state count query
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# Load worktree env (DATABASE_URL etc.) without exporting stray shell state.
set -a; source "$REPO_ROOT/.env"; set +a

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/$BRANCH/demo.md"
PROBE="docs/demos/$BRANCH/probe.py"

uvx showboat init "$DEMO_FILE" \
  "GitHub issue_comment webhooks no longer crash the AgentNotifierConsumer, and every registered worktree now carries a populated branch_name so the resolver's branch fallback actually works."

# --- Background ------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Bug scenario: every issue_comment webhook arrives with an empty head_branch. \
Live-prod worktrees had branch_name='' (MCP client never sent it), so the \
resolver's fallback ran WHERE branch_name='' AND status='online' and matched \
every live worktree at once → sqlalchemy.exc.MultipleResultsFound."

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

# --- Proof 3: register-time derivation ------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — branch_name populated on registration. AgentService derives the \
branch via 'git symbolic-ref --short HEAD' at the worktree path when the \
caller (the MCP client) does not supply one. Invoking it against this \
worktree returns the actual branch."

uvx showboat exec "$DEMO_FILE" bash "DATABASE_URL=\"$DATABASE_URL\" uv run python $PROBE derive"

# --- Proof 4: live-DB backfill -------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 4 — data backfill against the live cloglog DB (main shared instance, \
not the worktree's isolated DB). After running the Alembic migration, no \
online worktree row carries an empty branch_name — the data trap is closed."

uvx showboat exec "$DEMO_FILE" bash \
  "PGPASSWORD=cloglog_dev psql -h 127.0.0.1 -U cloglog -d cloglog -tA -c \"SELECT count(*) FROM worktrees WHERE status='online' AND (branch_name IS NULL OR branch_name='')\""

uvx showboat verify "$DEMO_FILE"
