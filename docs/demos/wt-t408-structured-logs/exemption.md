---
verdict: no_demo
diff_hash: 9315ac0333b7049de4d174f09f93c9e6107614c17d1890263b2ddafd81bd53e1
classifier: demo-classifier
generated_at: 2026-05-04T09:56:06Z
---

## Why no demo

The diff adds a new shared helper `src/shared/log_event.py`, wires structured log calls (`log_event`) into `src/agent/services.py`, `src/gateway/review_engine.py`, `src/gateway/review_loop.py`, and `src/gateway/webhook_dispatcher.py`, and configures log-level routing in `src/gateway/app.py`. All changes are purely additive logging/metrics instrumentation — no HTTP route decorator is added or changed, no React component or UI output changes, no MCP tool schema changes, and no CLI output changes. The strongest candidate for `needs_demo` was the `_run_review_agent` return-type change, but this is an internal refactor of a private method with no HTTP response shape or MCP tool surface changes.

## Changed files

- docs/demos/wt-t408-structured-logs/exemption.md
- src/agent/services.py
- src/gateway/app.py
- src/gateway/review_engine.py
- src/gateway/review_loop.py
- src/gateway/webhook_dispatcher.py
- src/shared/log_event.py
- tests/gateway/test_structured_logs.py
