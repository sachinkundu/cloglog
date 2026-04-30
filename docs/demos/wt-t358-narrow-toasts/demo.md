# Desktop toasts now fire only on operator-attention events; routine PR moves and clean shutdowns go silent.

*2026-04-30T06:31:37Z by Showboat 0.6.1*
<!-- showboat-id: 09fc0c76-4ba1-4813-a0a8-48500e504fb4 -->

Before: the inline notify-send call lived inside _handle_review_event so every TASK_STATUS_CHANGED -> review fired a desktop toast. With parallel worktrees that is one toast per PR open -- the operator stops reading them. The persisted Notification row + dashboard bell already covered the routine case; only the toast was noise.

Action 1: assert the inline notify-send call has been removed from _handle_review_event. Grep the post-T-358 source for asyncio.create_subprocess_exec inside that function -- the count must be zero.

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

Action 3: AGENT_UNREGISTERED filter. Default unregister (no reason) stays silent -- the public API path agents take after a successful merge. force_unregister and heartbeat_timeout reasons toast. Unknown reasons fall through to silent (the allowlist is the source of truth). Off-switch suppresses even non-clean reasons.

```bash
uv run --quiet python -c "
import asyncio, sys
sys.path.insert(0, \"tests/gateway\")
import test_notification_listener_toasts_on_unregister_filter as t
asyncio.run(t.test_clean_unregister_does_not_toast())
asyncio.run(t.test_force_unregister_toasts())
asyncio.run(t.test_heartbeat_timeout_toasts())
asyncio.run(t.test_unknown_reason_does_not_toast())
asyncio.run(t.test_off_switch_suppresses_non_clean_toast())
print(\"unregister filter: 5 invariants hold\")
"
```

```output
unregister filter: 5 invariants hold
```

After: routine status moves stay silent; force-unregister and heartbeat-timeout exits surface immediately. Operator off-switch (desktop_toast_enabled: false in .cloglog/config.yaml) suppresses every toast class without affecting the persisted Notification row or dashboard SSE.
