#!/usr/bin/env bash
# Demo: close-wave and reconcile now drive shutdown through the cooperative
# request_shutdown → agent_unregistered → force_unregister (fallback) flow.
# Called by `make demo`.
#
# Proof style: OK/FAIL booleans per step, scoped greps against the exact
# skill/doc files under audit. No repo-wide counts (unrelated future edits
# would bump them and break byte-exact `showboat verify`). No raw pytest
# output (timings are non-deterministic) — we capture only the pass count.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

HELPER="scripts/wait_for_agent_unregistered.py"
CLOSE_SKILL="plugins/cloglog/skills/close-wave/SKILL.md"
RECONCILE_SKILL="plugins/cloglog/skills/reconcile/SKILL.md"
LIFECYCLE="docs/design/agent-lifecycle.md"
MCP_TOOLS="mcp-server/src/tools.ts"
MCP_SERVER="mcp-server/src/server.ts"

uvx showboat init "$DEMO_FILE" \
  "close-wave and reconcile now ask worktree agents to shut themselves down cooperatively, only escalating to force_unregister on timeout."

# ────────────────────────────────────────────────────────────────────────────
# Section 1 — Helper behaviour (happy + timeout paths)
# ────────────────────────────────────────────────────────────────────────────

uvx showboat note "$DEMO_FILE" \
  "Step 1 — helper script exists and is executable."
uvx showboat exec "$DEMO_FILE" bash \
  'test -x '"$HELPER"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 2 — HAPPY PATH: write agent_unregistered to a fake inbox mid-wait; helper exits 0 so the skill proceeds to teardown without force_unregister."
uvx showboat exec "$DEMO_FILE" bash '
  TMP=$(mktemp -d)
  INBOX="$TMP/inbox"
  : > "$INBOX"
  SINCE=$(stat -c %s "$INBOX")
  ( sleep 0.3; echo "{\"type\":\"agent_unregistered\",\"worktree\":\"wt-coop-demo\",\"worktree_id\":\"00000000-0000-0000-0000-000000000001\",\"ts\":\"2026-04-22T00:00:00Z\",\"tasks_completed\":[\"T-220\"],\"artifacts\":{\"work_log\":\"/tmp/a\",\"learnings\":\"/tmp/b\"},\"reason\":\"all_assigned_tasks_complete\"}" >> "$INBOX" ) &
  set +e
  uv run python scripts/wait_for_agent_unregistered.py \
      --worktree wt-coop-demo \
      --inbox "$INBOX" \
      --since-offset "$SINCE" \
      --timeout 5 \
      --poll-interval 0.05 >/dev/null 2>&1
  rc=$?
  set -e
  wait
  rm -rf "$TMP"
  [ "$rc" = "0" ] && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 3 — TIMEOUT PATH: no event arrives; helper exits 1 so the skill falls back to force_unregister and records the fallback."
uvx showboat exec "$DEMO_FILE" bash '
  TMP=$(mktemp -d)
  INBOX="$TMP/inbox"
  : > "$INBOX"
  SINCE=$(stat -c %s "$INBOX")
  set +e
  uv run python scripts/wait_for_agent_unregistered.py \
      --worktree wt-coop-demo \
      --inbox "$INBOX" \
      --since-offset "$SINCE" \
      --timeout 0.3 \
      --poll-interval 0.05 >/dev/null 2>&1
  rc=$?
  set -e
  rm -rf "$TMP"
  [ "$rc" = "1" ] && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 3b — RACE CLOSED: agent_unregistered lands BEFORE the helper starts (fast-agent scenario the review flagged); helper still exits 0 because the caller captured the offset before request_shutdown."
uvx showboat exec "$DEMO_FILE" bash '
  TMP=$(mktemp -d)
  INBOX="$TMP/inbox"
  : > "$INBOX"
  SINCE=$(stat -c %s "$INBOX")
  # Event lands BEFORE helper invocation — simulates the racy fast-agent path.
  echo "{\"type\":\"agent_unregistered\",\"worktree\":\"wt-coop-demo\",\"worktree_id\":\"00000000-0000-0000-0000-000000000002\",\"ts\":\"2026-04-22T00:00:01Z\",\"tasks_completed\":[\"T-220\"],\"artifacts\":{\"work_log\":\"/tmp/a\",\"learnings\":\"/tmp/b\"},\"reason\":\"all_assigned_tasks_complete\"}" >> "$INBOX"
  set +e
  uv run python scripts/wait_for_agent_unregistered.py \
      --worktree wt-coop-demo \
      --inbox "$INBOX" \
      --since-offset "$SINCE" \
      --timeout 2 \
      --poll-interval 0.05 >/dev/null 2>&1
  rc=$?
  set -e
  rm -rf "$TMP"
  [ "$rc" = "0" ] && echo OK || echo FAIL'

# ────────────────────────────────────────────────────────────────────────────
# Section 2 — close-wave SKILL wiring
# ────────────────────────────────────────────────────────────────────────────

uvx showboat note "$DEMO_FILE" \
  "Step 4 — close-wave calls mcp__cloglog__request_shutdown (tier 1)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "mcp__cloglog__request_shutdown" '"$CLOSE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 5 — close-wave waits for agent_unregistered via the helper WITH --since-offset (closes the race flagged in PR review)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "scripts/wait_for_agent_unregistered.py" '"$CLOSE_SKILL"' && grep -q -- "--since-offset" '"$CLOSE_SKILL"' && grep -q "SINCE_OFFSET" '"$CLOSE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 5b — close-wave resolves the supervisor inbox via --git-common-dir, not --show-toplevel (safe inside a worktree)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "git-common-dir" '"$CLOSE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 6 — close-wave falls back to mcp__cloglog__force_unregister only on timeout."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "mcp__cloglog__force_unregister" '"$CLOSE_SKILL"' && grep -q "Step 5c" '"$CLOSE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 7 — close-wave no longer kill-by-PIDs the launcher (the old Step 5 is gone)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -qE "^# Kill gracefully|^kill <pids>" '"$CLOSE_SKILL"' && echo FAIL || echo OK'

# ────────────────────────────────────────────────────────────────────────────
# Section 3 — reconcile SKILL wiring
# ────────────────────────────────────────────────────────────────────────────

uvx showboat note "$DEMO_FILE" \
  "Step 8 — reconcile calls mcp__cloglog__request_shutdown for wedged/merged cases."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "mcp__cloglog__request_shutdown" '"$RECONCILE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 9 — reconcile uses the cooperative-wait helper with --since-offset."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "scripts/wait_for_agent_unregistered.py" '"$RECONCILE_SKILL"' && grep -q -- "--since-offset" '"$RECONCILE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 9b — reconcile resolves MAIN_INBOX via --git-common-dir (safe inside a worktree; CLAUDE.md-documented pitfall)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "git-common-dir" '"$RECONCILE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 10 — reconcile covers Case A (pr_merged), Case B (wedged), Case C (orphaned) — all derivable from list_worktrees."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "Case A" '"$RECONCILE_SKILL"' && grep -q "Case B" '"$RECONCILE_SKILL"' && grep -q "Case C" '"$RECONCILE_SKILL"' && grep -q "mcp__cloglog__list_worktrees" '"$RECONCILE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 11 — reconcile keeps auto-fix (no separate fix step)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "Always fix issues automatically" '"$RECONCILE_SKILL"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 11b — NEW MCP tool: list_worktrees is exposed by the MCP server and wraps GET /projects/{id}/worktrees (closes the supervisor-restart gap flagged in PR review round 2)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "list_worktrees" '"$MCP_TOOLS"' && grep -q "list_worktrees" '"$MCP_SERVER"' && grep -q "/projects/.*\\/worktrees" '"$MCP_TOOLS"' && echo OK || echo FAIL'

uvx showboat note "$DEMO_FILE" \
  "Step 11c — close-wave uses mcp__cloglog__list_worktrees to map filesystem paths → worktree_ids (doesn't rely on the ephemeral supervisor inbox)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "mcp__cloglog__list_worktrees" '"$CLOSE_SKILL"' && echo OK || echo FAIL'

# ────────────────────────────────────────────────────────────────────────────
# Section 4 — agent-lifecycle doc updated
# ────────────────────────────────────────────────────────────────────────────

uvx showboat note "$DEMO_FILE" \
  "Step 12 — lifecycle doc's T-220 CONSUMER GAP is removed (the consumer is wired now)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "CONSUMER GAP — T-220" '"$LIFECYCLE"' && echo FAIL || echo OK'

uvx showboat note "$DEMO_FILE" \
  "Step 13 — lifecycle doc preserves the T-217 invariant (close-tab does not signal children)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -q "T-217" '"$LIFECYCLE"' && grep -q "zellij action close-tab" '"$LIFECYCLE"' && echo OK || echo FAIL'

# ────────────────────────────────────────────────────────────────────────────
# Section 5 — regression tests
# ────────────────────────────────────────────────────────────────────────────

uvx showboat note "$DEMO_FILE" \
  "Step 14 — helper regression tests pass (capturing the pass count only — timings are stripped for determinism)."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/test_wait_for_agent_unregistered.py -q 2>&1 | grep -oE "[0-9]+ passed"'

uvx showboat verify "$DEMO_FILE"
