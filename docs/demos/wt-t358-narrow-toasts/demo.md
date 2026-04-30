# Desktop toasts now fire only on operator-attention events; routine PR moves go silent.

*2026-04-30T06:01:02Z by Showboat 0.6.1*
<!-- showboat-id: 02764515-d87f-4f06-9f25-20e2866fd7a6 -->

Before: the inline notify-send call lived inside _handle_review_event so every TASK_STATUS_CHANGED -> review fired a desktop toast. With parallel worktrees that is one toast per PR open -- the operator stops reading them. The persisted Notification row + dashboard bell already covered the routine case; only the toast was noise.

Action 1: assert the inline notify-send call has been removed from _handle_review_event. We grep the post-T-358 source for asyncio.create_subprocess_exec inside that function -- the count must be zero.

```bash
python3 -c "
import ast, pathlib
src = pathlib.Path(\"src/gateway/notification_listener.py\").read_text()
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == \"_handle_review_event\")
calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
hits = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == \"create_subprocess_exec\"]
print(f\"create_subprocess_exec calls in _handle_review_event: {len(hits)}\")
assert len(hits) == 0, \"regression: inline notify-send is back\"
"
```

```output
create_subprocess_exec calls in _handle_review_event: 0
```

Action 2: drive the dispatcher with TASK_STATUS_CHANGED -> review; the persisted row + NOTIFICATION_CREATED SSE still fire, the toast does NOT.

```bash
uv run --quiet python -c "
import asyncio, sys
sys.path.insert(0, \"tests/gateway\")
import test_notification_listener_does_not_toast_on_review_transition as t
asyncio.run(t.test_review_transition_creates_row_and_sse_but_no_toast())
print(\"absence-pin holds: review move did not call notify-send\")
"
```

```output
absence-pin holds: review move did not call notify-send
```

Action 3: drive the dispatcher with AGENT_BLOCKED; the operator-attention path DOES toast, with a body that names the block reason.

```bash
uv run --quiet python -c "
import asyncio, sys
sys.path.insert(0, \"tests/gateway\")
import test_notification_listener_toasts_on_agent_blocked as t
asyncio.run(t.test_agent_blocked_event_fires_one_notify_send())
asyncio.run(t.test_agent_blocked_event_skipped_when_disabled())
print(\"agent_blocked toasts; off-switch suppresses\")
"
```

```output
agent_blocked toasts; off-switch suppresses
```

Action 4: a single CHANGES_REQUESTED is normal (auto-fix). Two consecutive on the same PR means the agent cannot fix it -- the tracker fires once.

```bash
uv run --quiet python -c "
import sys
sys.path.insert(0, \"tests/gateway\")
import test_notification_listener_toasts_on_changes_requested_repeat as t
t.test_single_changes_requested_does_not_trigger_repeat()
t.test_two_consecutive_changes_requested_triggers_repeat()
t.test_intervening_approval_resets_the_streak()
t.test_streaks_are_tracked_per_pr()
print(\"two-consecutive rule: 4 invariants hold\")
"
```

```output
two-consecutive rule: 4 invariants hold
```

Action 5: auto-merge stall debouncer -- first ci_not_green poll is silent; once 15 min has elapsed without state change, ONE toast fires; subsequent polls stay silent until the PR transitions out and clear() is called.

```bash
uv run --quiet python -c "
import sys
sys.path.insert(0, \"tests/gateway\")
import test_notification_listener_toasts_on_auto_merge_stall as t
t.test_first_poll_does_not_trip()
t.test_threshold_crossed_trips_exactly_once()
t.test_clear_resets_and_allows_a_future_stall_toast()
t.test_per_pr_scoping()
print(\"stall debouncer: 4 invariants hold\")
"
```

```output
stall debouncer: 4 invariants hold
```

After: routine status moves stay silent; agent_blocked / repeat CHANGES_REQUESTED / auto-merge stall surface immediately. Operator off-switch (desktop_toast_enabled: false in .cloglog/config.yaml) suppresses every toast class without affecting the persisted Notification row or dashboard SSE.
