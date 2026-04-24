#!/usr/bin/env bash
# Demo for T-287: shrink CLAUDE.md and ship a silent-failure invariants
# manifest with a regression target. Verify-safe: grep booleans and
# line-count checks only, no pytest / DB / network.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "CLAUDE.md is smaller and every silent-failure gotcha now points at a pin test runnable via \`make invariants\`."

# ==================================================================
uvx showboat note "$DEMO_FILE" "### CLAUDE.md is no longer a dumping ground

The pre-change file carried 230+ lines of scenario-specific incident
replays. This PR replaces the long gotcha section with a short pointer
to \`docs/invariants.md\`, where each rule is backed by a named pin
test. Agents run \`make invariants\` before pushing work in a sensitive
area; CI runs them as part of \`make test\`."

# ----- CLAUDE.md shrank substantially -----
uvx showboat exec "$DEMO_FILE" bash \
  'lines=$(wc -l < CLAUDE.md)
   [ "$lines" -lt 100 ] && echo "claude_md_lines=${lines}_under_100" || echo "claude_md_lines=${lines}_TOO_LONG"'

# ----- Canonical T-213 MCP-failure sentence preserved verbatim -----
uvx showboat exec "$DEMO_FILE" bash \
  'grep -qF "Halt on any MCP failure: startup unavailability emits" CLAUDE.md \
     && echo "mcp_rule_verbatim=yes" || echo "mcp_rule_verbatim=MISSING"'

# ----- Architecture section now lists 5 contexts (adds Review) -----
uvx showboat exec "$DEMO_FILE" bash \
  'grep -cE "^- \*\*(Board|Agent|Document|Review|Gateway)\*\*" CLAUDE.md \
     | awk "{print \"claude_md_context_bullets=\" \$1}"'

# ==================================================================
uvx showboat note "$DEMO_FILE" "### The manifest exists and names every pin test

\`docs/invariants.md\` lists each silent-failure invariant with the
pytest path that guards it. Below: the manifest references every test
the new \`make invariants\` target runs."

# ----- Manifest exists and mentions the regression target -----
uvx showboat exec "$DEMO_FILE" bash \
  'test -f docs/invariants.md && echo "manifest_exists=yes" || echo "manifest_exists=MISSING"
   grep -qF "make invariants" docs/invariants.md && echo "manifest_references_make_target=yes" || echo "manifest_references_make_target=MISSING"'

# ----- Each referenced pin test file resolves on disk -----
uvx showboat exec "$DEMO_FILE" bash \
  'for t in \
      tests/test_on_worktree_create_backend_url.py \
      tests/test_mcp_json_no_secret.py \
      tests/test_no_destructive_migrations.py \
      tests/agent/test_integration.py \
      tests/agent/test_unit.py \
      tests/e2e/test_access_control.py \
      tests/gateway/test_review_engine.py; do
     [ -f "$t" ] && echo "pin_test_file_exists=${t}" || echo "pin_test_file_missing=${t}"
   done'

# ----- Each referenced pin class / test name resolves inside its file -----
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "class TestResolvePrReviewRoot" tests/gateway/test_review_engine.py \
     && echo "resolve_pr_class=yes" || echo "resolve_pr_class=MISSING"
   grep -q "class TestLatestCodexReviewIsApproval" tests/gateway/test_review_engine.py \
     && echo "severe_severities_class=yes" || echo "severe_severities_class=MISSING"
   grep -q "def test_force_unregister_rejects_agent_token" tests/agent/test_integration.py \
     && echo "force_unregister_rejects_agent=yes" || echo "force_unregister_rejects_agent=MISSING"
   grep -q "def test_register_reconnect_preserves_branch_when_caller_sends_empty" tests/agent/test_unit.py \
     && echo "upsert_preserve_empty=yes" || echo "upsert_preserve_empty=MISSING"
   grep -q "async def test_worktrees_with_invalid_mcp_bearer_is_rejected" tests/e2e/test_access_control.py \
     && echo "mcp_bearer_rejected=yes" || echo "mcp_bearer_rejected=MISSING"
   grep -q "def test_hook_does_not_invoke_python_yaml" tests/test_on_worktree_create_backend_url.py \
     && echo "hook_no_python_yaml=yes" || echo "hook_no_python_yaml=MISSING"'

# ==================================================================
uvx showboat note "$DEMO_FILE" "### The \`make invariants\` target lists the curated set

One place to run the regression suite, one place to extend when a new
silent-failure class lands."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "^invariants:" Makefile && echo "make_target_declared=yes" || echo "make_target_declared=MISSING"
   grep -q "test_no_destructive_migrations" Makefile && echo "target_runs_destructive_mig_test=yes" || echo "target_runs_destructive_mig_test=MISSING"
   grep -q "TestResolvePrReviewRoot" Makefile && echo "target_runs_resolve_pr_class=yes" || echo "target_runs_resolve_pr_class=MISSING"'

# ==================================================================
uvx showboat note "$DEMO_FILE" "### Structural DDD rules moved to ddd-reviewer

Router registration, Gateway-owns-no-tables, supervisor endpoints
rejecting agent tokens, and MCP-cred Depends live in the ddd-reviewer
subagent — it already reviews contracts, now it also reviews
implementation PRs for these silent boundary violations."

uvx showboat exec "$DEMO_FILE" bash \
  'DDD=.claude/agents/ddd-reviewer.md
   grep -q "Gateway owns no tables" "$DDD" && echo "ddd_gateway_no_tables=yes" || echo "ddd_gateway_no_tables=MISSING"
   grep -q "Routers must be registered in \`src/gateway/app.py\`" "$DDD" && echo "ddd_router_registration=yes" || echo "ddd_router_registration=MISSING"
   grep -q "Destructive endpoints that must reject self-initiation need \`McpOrProject\`, not \`SupervisorAuth\`" "$DDD" && echo "ddd_reject_agent_tokens=yes" || echo "ddd_reject_agent_tokens=MISSING"
   grep -q "CurrentMcpService" "$DDD" && echo "ddd_mcp_depends=yes" || echo "ddd_mcp_depends=MISSING"'

# ==================================================================
uvx showboat note "$DEMO_FILE" "### New destructive-migration trip-wire

The one invariant without existing coverage now has a pin test:
\`tests/test_no_destructive_migrations.py\` scans every
\`src/alembic/versions/*.py\` \`upgrade()\` body for destructive shapes
that historically shipped broken. Legitimate additive backfill
(e.g. \`UPDATE tasks SET task_type = ...\` after adding the column)
is unaffected."

uvx showboat exec "$DEMO_FILE" bash \
  'T=tests/test_no_destructive_migrations.py
   grep -q "DESTRUCTIVE_PATTERNS" "$T" && echo "destructive_patterns=yes" || echo "destructive_patterns=MISSING"
   grep -q "ALLOWED_DESTRUCTIVE_MIGRATIONS" "$T" && echo "allowlist_present=yes" || echo "allowlist_present=MISSING"
   grep -q "def _extract_upgrade_body" "$T" && echo "upgrade_only_scope=yes" || echo "upgrade_only_scope=MISSING"
   python3 -c "
import sys
sys.path.insert(0, \"tests\")
import test_no_destructive_migrations as m
violations = []
for path in sorted(m.VERSIONS_DIR.glob(\"*.py\")):
    if path.name == \"__init__.py\":
        continue
    body = m._extract_upgrade_body(path.read_text())
    for pat, _tables in m.DESTRUCTIVE_PATTERNS:
        if pat.search(body):
            violations.append(path.name)
print(f\"current_migration_violations={len(violations)}\")
"'

# ==================================================================
uvx showboat verify "$DEMO_FILE"
