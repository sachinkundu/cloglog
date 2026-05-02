---
verdict: no_demo
diff_hash: f566b6a2e278c965ed608e8598810b050515173454336f6eb4f3a869060078a5
classifier: demo-classifier
generated_at: 2026-05-02T00:00:00Z
---

## Why no demo

Signal: diff is logging-only in production code — `src/agent/routes.py` adds
a `logger.warning` for an unassigned close-off path, and
`src/gateway/webhook_consumers.py` adds warning/debug log lines on webhook
drop branches. No router decorators added/changed, no response shapes
touched, no schemas modified. Test files
(`tests/agent/test_close_off_task.py`, `tests/gateway/test_webhook_consumers.py`)
are test-only. Strongest needs_demo candidate considered: the new behaviour
around close-off task assignment, but the production change is only a log
line — control flow and response remain identical. Counterfactual: if the
route had begun assigning `worktree_id` to the main agent (changing what
`GET /agents/{wt}/tasks` returns to the supervisor) rather than just logging
when it can't, that would be user-observable and flip to needs_demo.

## Changed files

- src/agent/routes.py
- src/gateway/webhook_consumers.py
- tests/agent/test_close_off_task.py
- tests/gateway/test_webhook_consumers.py
