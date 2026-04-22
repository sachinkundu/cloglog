#!/usr/bin/env bash
# Demo: T-213 — "Stop on MCP failure" rule broadened to cover runtime tool errors.
# Called by make demo (server + DB already running, but this demo does not use them).
#
# Strategy: the rule is docs + plugin text. Proof is a per-file OK/FAIL boolean
# showing the canonical sentence is present in each file the rule is supposed
# to land in, plus a second pass showing the mcp_tool_error event shape lives
# in the authoritative location, plus the backstop test passing. Per CLAUDE.md
# demo-determinism rules, every captured output is a deterministic boolean or
# a reduced pass-count — no pytest timings, no grep counts that could tick on
# unrelated future edits.
#
# The canonical sentence is checked in alongside this script as
# `canonical-rule.txt` (no trailing newline) so `showboat verify` can re-run
# every check idempotently.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"
CANONICAL="$DEMO_DIR/canonical-rule.txt"

# `uvx showboat init` refuses to overwrite an existing demo.md (T-222
# learnings, docs/work-logs/2026-04-19-t222-lifecycle-spec-learnings.md).
# Remove any prior run's output so `make demo` is idempotent and
# `showboat verify` can re-run cleanly in CI or on a fresh checkout.
rm -f "$DEMO_FILE"

uvx showboat init "$DEMO_FILE" \
  "Worktree agents now halt on any MCP failure — startup OR runtime — emitting a typed inbox event (mcp_unavailable vs mcp_tool_error) so the main agent knows whether the agent has exited or is waiting for guidance."

uvx showboat note "$DEMO_FILE" \
"### Stakeholder framing

Before T-213 the 'Stop on MCP failure' rule covered only *startup* unavailability
(ToolSearch returning no matches). If an MCP tool call succeeded in reaching the
server but returned a 409 state guard, a 5xx, or a schema error mid-task, the
written rule was silent and different skills gave contradictory guidance. Agents
had silently shipped broken work by treating a 409 as 'proceed anyway'.

After T-213 the rule distinguishes three cases with distinct responses:

1. **Startup unavailability** → emit \`mcp_unavailable\` and exit (agent cannot participate).
2. **Runtime tool error** → emit \`mcp_tool_error\` and wait on inbox for main-agent guidance.
3. **Transient network error** → one backoff retry, then escalate to \`mcp_tool_error\`.

This demo proves the broadened rule text landed in every place an agent or main
agent reader would look, and that a backstop test pins the canonical sentence
byte-exact so it cannot silently drift back."

# --- Part 1: canonical sentence is present in every required file --------------
# Per CLAUDE.md determinism rule: per-file OK/FAIL boolean, NOT a repo-wide grep count.

uvx showboat note "$DEMO_FILE" "### Canonical rule sentence — per-file presence check

Each check greps the exact canonical sentence from \`canonical-rule.txt\` against
one authoritative location. An OK line proves the sentence is present verbatim;
a FAIL line would exit non-zero and be caught by \`showboat verify\`."

uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qFf docs/demos/wt-e1-mcp-failure-rule/canonical-rule.txt docs/design/agent-lifecycle.md; then echo "OK   docs/design/agent-lifecycle.md"; else echo "FAIL docs/design/agent-lifecycle.md"; exit 1; fi'
uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qFf docs/demos/wt-e1-mcp-failure-rule/canonical-rule.txt plugins/cloglog/templates/claude-md-fragment.md; then echo "OK   plugins/cloglog/templates/claude-md-fragment.md"; else echo "FAIL plugins/cloglog/templates/claude-md-fragment.md"; exit 1; fi'
uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qFf docs/demos/wt-e1-mcp-failure-rule/canonical-rule.txt plugins/cloglog/skills/setup/SKILL.md; then echo "OK   plugins/cloglog/skills/setup/SKILL.md"; else echo "FAIL plugins/cloglog/skills/setup/SKILL.md"; exit 1; fi'
uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qFf docs/demos/wt-e1-mcp-failure-rule/canonical-rule.txt plugins/cloglog/skills/launch/SKILL.md; then echo "OK   plugins/cloglog/skills/launch/SKILL.md"; else echo "FAIL plugins/cloglog/skills/launch/SKILL.md"; exit 1; fi'
uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qFf docs/demos/wt-e1-mcp-failure-rule/canonical-rule.txt CLAUDE.md; then echo "OK   CLAUDE.md"; else echo "FAIL CLAUDE.md"; exit 1; fi'

# --- Part 2: mcp_tool_error event shape lives in agent-lifecycle.md §4.1 -------

uvx showboat note "$DEMO_FILE" "### Event shape — \`mcp_tool_error\` is documented in the authoritative spec

The agent-lifecycle.md §4.1 MUST carry a JSON shape for the new event so
emitters and consumers cannot drift. Each check greps one load-bearing field."

uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qF "\"type\": \"mcp_tool_error\"" docs/design/agent-lifecycle.md; then echo "OK   type field present"; else echo "FAIL type field missing"; exit 1; fi'
uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qF "\"reason\": \"runtime_tool_error\"" docs/design/agent-lifecycle.md; then echo "OK   reason=runtime_tool_error present"; else echo "FAIL reason field missing"; exit 1; fi'
uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qF "\"worktree_id\"" docs/design/agent-lifecycle.md; then echo "OK   worktree_id field present"; else echo "FAIL worktree_id field missing"; exit 1; fi'

# --- Part 3: outbound events table distinguishes the two event types ----------

uvx showboat note "$DEMO_FILE" "### Outbound events table — both event types listed distinctly

Before T-213 only \`mcp_unavailable\` existed, and it meant 'any MCP failure'.
After T-213 the table distinguishes startup (\`mcp_unavailable\`) from runtime
(\`mcp_tool_error\`) and carries a separate row for each."

uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qF "| \`mcp_unavailable\` |" docs/design/agent-lifecycle.md; then echo "OK   mcp_unavailable row present"; else echo "FAIL mcp_unavailable row missing"; exit 1; fi'
uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qF "| \`mcp_tool_error\` |" docs/design/agent-lifecycle.md; then echo "OK   mcp_tool_error row present"; else echo "FAIL mcp_tool_error row missing"; exit 1; fi'

# --- Part 4: backstop test passes ---------------------------------------------

uvx showboat note "$DEMO_FILE" "### Backstop test — \`tests/test_mcp_failure_rule_wording.py\` pins the rule

Three assertions, one per invariant (canonical sentence presence,
\`mcp_tool_error\` shape documented, outbound events table distinction). The
demo imports the test module directly with \`python3\` instead of running it
through \`pytest\` — \`tests/conftest.py\` has a session-autouse fixture that
connects to Postgres on \`localhost:5432\`, which is NOT available when
\`scripts/check-demo.sh\` invokes \`uvx showboat verify\` (it does not start
the dev DB). Importing the module bypasses conftest entirely and keeps this
check self-contained for re-verification on a clean checkout."

uvx showboat exec "$DEMO_FILE" bash \
  'python3 -c "import sys; sys.path.insert(0, \"tests\"); import test_mcp_failure_rule_wording as t; t.test_canonical_rule_appears_verbatim_in_each_location(); t.test_mcp_tool_error_event_is_documented_in_agent_lifecycle(); t.test_outbound_events_table_distinguishes_unavailable_from_tool_error(); print(\"3 assertions passed\")"'

# --- Part 5: regression — pre-T-213 wording is gone ---------------------------

uvx showboat note "$DEMO_FILE" "### Regression check — pre-T-213 wording is gone

Before T-213 the outbound events table collapsed all MCP failures into one row:
\`| \`mcp_unavailable\` | Any MCP failure (Section 4) ... |\`. Confirm that row
is gone so a future edit cannot silently revert the broadening."

uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qF "| \`mcp_unavailable\` | Any MCP failure" docs/design/agent-lifecycle.md; then echo "FAIL pre-T-213 row still present"; exit 1; else echo "OK   pre-T-213 Any MCP failure wording removed"; fi'

# --- Verify ------------------------------------------------------------------

uvx showboat verify "$DEMO_FILE"
