#!/usr/bin/env bash
# Demo: Desktop toasts narrowed to operator-attention events.
# T-358 ships two rules:
#   1. TASK_STATUS_CHANGED -> review no longer fires notify-send.
#   2. AGENT_UNREGISTERED toasts only on known-non-clean reasons; clean
#      shutdowns via the public API stay silent.
# Pure-process demo -- doesn't touch backend or DB.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Desktop toasts now fire only on operator-attention events; routine PR moves and clean shutdowns go silent."

uvx showboat note "$DEMO_FILE" \
  "Before: the inline notify-send call lived inside _handle_review_event so every TASK_STATUS_CHANGED -> review fired a desktop toast. With parallel worktrees that is one toast per PR open -- the operator stops reading them. The persisted Notification row + dashboard bell already covered the routine case; only the toast was noise."

uvx showboat note "$DEMO_FILE" \
  "Action 1: assert the inline notify-send call has been removed from _handle_review_event. Grep the post-T-358 source for asyncio.create_subprocess_exec inside that function -- the count must be zero."
uvx showboat exec "$DEMO_FILE" bash \
  'python3 -c "
import ast, pathlib
src = pathlib.Path(\"src/gateway/notification_listener.py\").read_text()
tree = ast.parse(src)
fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == \"_handle_review_event\")
calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
hits = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == \"create_subprocess_exec\"]
print(f\"create_subprocess_exec calls in _handle_review_event: {len(hits)}\")
assert len(hits) == 0, \"regression: inline notify-send is back\"
"'

uvx showboat note "$DEMO_FILE" \
  "Action 2: drive the dispatcher with TASK_STATUS_CHANGED -> review; the persisted row + NOTIFICATION_CREATED SSE still fire, the toast does NOT."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run --quiet python -c "
import asyncio, sys
sys.path.insert(0, \"tests/gateway\")
import test_notification_listener_does_not_toast_on_review_transition as t
asyncio.run(t.test_review_transition_creates_row_and_sse_but_no_toast())
print(\"absence-pin holds: review move did not call notify-send\")
"'

uvx showboat note "$DEMO_FILE" \
  "Action 3: AGENT_UNREGISTERED filter. Default unregister (no reason) stays silent -- the public API path agents take after a successful merge. force_unregister and heartbeat_timeout reasons toast. Unknown reasons fall through to silent (the allowlist is the source of truth). Off-switch suppresses even non-clean reasons."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run --quiet python -c "
import asyncio, sys
sys.path.insert(0, \"tests/gateway\")
import test_notification_listener_toasts_on_unregister_filter as t
asyncio.run(t.test_clean_unregister_does_not_toast())
asyncio.run(t.test_force_unregister_toasts())
asyncio.run(t.test_heartbeat_timeout_toasts())
asyncio.run(t.test_unknown_reason_does_not_toast())
asyncio.run(t.test_off_switch_suppresses_non_clean_toast())
print(\"unregister filter: 5 invariants hold\")
"'

uvx showboat note "$DEMO_FILE" \
  "After: routine status moves stay silent; force-unregister and heartbeat-timeout exits surface immediately. Operator off-switch (desktop_toast_enabled: false in .cloglog/config.yaml) suppresses every toast class without affecting the persisted Notification row or dashboard SSE."

uvx showboat verify "$DEMO_FILE"
