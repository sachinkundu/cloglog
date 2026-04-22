# close-wave and reconcile now ask worktree agents to shut themselves down cooperatively, only escalating to force_unregister on timeout.

*2026-04-22T08:19:33Z by Showboat 0.6.1*
<!-- showboat-id: 416eab78-0b1e-4bf4-8de8-240c2e1efdcb -->

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
  ( sleep 0.3; echo "{\"type\":\"agent_unregistered\",\"worktree\":\"wt-coop-demo\",\"worktree_id\":\"00000000-0000-0000-0000-000000000001\",\"ts\":\"2026-04-22T00:00:00Z\",\"tasks_completed\":[\"T-220\"],\"artifacts\":{\"work_log\":\"/tmp/a\",\"learnings\":\"/tmp/b\"},\"reason\":\"all_assigned_tasks_complete\"}" >> "$INBOX" ) &
  set +e
  uv run python scripts/wait_for_agent_unregistered.py \
      --worktree wt-coop-demo \
      --inbox "$INBOX" \
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
  set +e
  uv run python scripts/wait_for_agent_unregistered.py \
      --worktree wt-coop-demo \
      --inbox "$INBOX" \
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

Step 4 — close-wave calls mcp__cloglog__request_shutdown (tier 1).

```bash
grep -q "mcp__cloglog__request_shutdown" plugins/cloglog/skills/close-wave/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 5 — close-wave waits for agent_unregistered via the helper.

```bash
grep -q "scripts/wait_for_agent_unregistered.py" plugins/cloglog/skills/close-wave/SKILL.md && echo OK || echo FAIL
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

Step 9 — reconcile uses the cooperative-wait helper.

```bash
grep -q "scripts/wait_for_agent_unregistered.py" plugins/cloglog/skills/reconcile/SKILL.md && echo OK || echo FAIL
```

```output
OK
```

Step 10 — reconcile enumerates Case A (pr_merged), Case B (wedged), Case C (orphaned).

```bash
grep -q "Case A" plugins/cloglog/skills/reconcile/SKILL.md && grep -q "Case B" plugins/cloglog/skills/reconcile/SKILL.md && grep -q "Case C" plugins/cloglog/skills/reconcile/SKILL.md && echo OK || echo FAIL
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
6 passed
```
