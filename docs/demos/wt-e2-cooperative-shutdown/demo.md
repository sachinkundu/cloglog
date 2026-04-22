# close-wave and reconcile now ask worktree agents to shut themselves down cooperatively, only escalating to force_unregister on timeout.

*2026-04-22T08:51:20Z by Showboat 0.6.1*
<!-- showboat-id: b74acded-2d7b-479c-8533-349e45366c9d -->

Step 1 — helper script exists and is executable.

```bash
test -x scripts/wait_for_agent_unregistered.py && echo OK || echo FAIL
```

```output
OK
```

Step 2 — HAPPY PATH: write agent_unregistered to a fake inbox mid-wait; helper exits 0 so the skill proceeds to teardown without force_unregister.

```bash

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
  [ "$rc" = "0" ] && echo OK || echo FAIL
```

```output
OK
```

Step 3 — TIMEOUT PATH: no event arrives; helper exits 1 so the skill falls back to force_unregister and records the fallback.

```bash

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
  [ "$rc" = "1" ] && echo OK || echo FAIL
```

```output
OK
```

Step 3b — RACE CLOSED: agent_unregistered lands BEFORE the helper starts (fast-agent scenario the review flagged); helper still exits 0 because the caller captured the offset before request_shutdown.

```bash

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
  [ "$rc" = "0" ] && echo OK || echo FAIL
```

```output
OK
```

Step 4 — close-wave calls mcp__cloglog__request_shutdown (tier 1).

```bash
grep -q "mcp__cloglog__request_shutdown" plugins/cloglog/skills/close-wave/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 5 — close-wave waits for agent_unregistered via the helper WITH --since-offset (closes the race flagged in PR review).

```bash
grep -q "scripts/wait_for_agent_unregistered.py" plugins/cloglog/skills/close-wave/SKILL.md && grep -q -- "--since-offset" plugins/cloglog/skills/close-wave/SKILL.md && grep -q "SINCE_OFFSET" plugins/cloglog/skills/close-wave/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 5b — close-wave resolves the supervisor inbox via --git-common-dir, not --show-toplevel (safe inside a worktree).

```bash
grep -q "git-common-dir" plugins/cloglog/skills/close-wave/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 6 — close-wave falls back to mcp__cloglog__force_unregister only on timeout.

```bash
grep -q "mcp__cloglog__force_unregister" plugins/cloglog/skills/close-wave/SKILL.md && grep -q "Step 5c" plugins/cloglog/skills/close-wave/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 7 — close-wave no longer kill-by-PIDs the launcher (the old Step 5 is gone).

```bash
grep -qE "^# Kill gracefully|^kill <pids>" plugins/cloglog/skills/close-wave/SKILL.md && echo FAIL || echo OK
```

```output
OK
```

Step 8 — reconcile calls mcp__cloglog__request_shutdown for wedged/merged cases.

```bash
grep -q "mcp__cloglog__request_shutdown" plugins/cloglog/skills/reconcile/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 9 — reconcile uses the cooperative-wait helper with --since-offset.

```bash
grep -q "scripts/wait_for_agent_unregistered.py" plugins/cloglog/skills/reconcile/SKILL.md && grep -q -- "--since-offset" plugins/cloglog/skills/reconcile/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 9b — reconcile resolves MAIN_INBOX via --git-common-dir (safe inside a worktree; CLAUDE.md-documented pitfall).

```bash
grep -q "git-common-dir" plugins/cloglog/skills/reconcile/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 10 — reconcile covers Case A (pr_merged), Case B (wedged), Case C (orphaned) — all derivable from list_worktrees.

```bash
grep -q "Case A" plugins/cloglog/skills/reconcile/SKILL.md && grep -q "Case B" plugins/cloglog/skills/reconcile/SKILL.md && grep -q "Case C" plugins/cloglog/skills/reconcile/SKILL.md && grep -q "mcp__cloglog__list_worktrees" plugins/cloglog/skills/reconcile/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 11 — reconcile keeps auto-fix (no separate fix step).

```bash
grep -q "Always fix issues automatically" plugins/cloglog/skills/reconcile/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 11b — NEW MCP tool: list_worktrees is exposed by the MCP server and wraps GET /projects/{id}/worktrees (closes the supervisor-restart gap flagged in PR review round 2).

```bash
grep -q "list_worktrees" mcp-server/src/tools.ts && grep -q "list_worktrees" mcp-server/src/server.ts && grep -q "/projects/.*\\/worktrees" mcp-server/src/tools.ts && echo OK || echo FAIL
```

```output
OK
```

Step 11c — close-wave uses mcp__cloglog__list_worktrees to map filesystem paths → worktree_ids (doesn't rely on the ephemeral supervisor inbox).

```bash
grep -q "mcp__cloglog__list_worktrees" plugins/cloglog/skills/close-wave/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 12 — lifecycle doc's T-220 CONSUMER GAP is removed (the consumer is wired now).

```bash
grep -q "CONSUMER GAP — T-220" docs/design/agent-lifecycle.md && echo FAIL || echo OK
```

```output
OK
```

Step 13 — lifecycle doc preserves the T-217 invariant (close-tab does not signal children).

```bash
grep -q "T-217" docs/design/agent-lifecycle.md && grep -q "zellij action close-tab" docs/design/agent-lifecycle.md && echo OK || echo FAIL
```

```output
OK
```

Step 14 — helper regression tests pass (capturing the pass count only — timings are stripped for determinism).

```bash
uv run pytest tests/test_wait_for_agent_unregistered.py -q 2>&1 | grep -oE "[0-9]+ passed"
```

```output
8 passed
```
