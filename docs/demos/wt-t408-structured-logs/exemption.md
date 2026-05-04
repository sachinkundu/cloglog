---
verdict: no_demo
diff_hash: 07c21a95116317e586fbea8edc3728619870bcf67c46c9634f9a1f8b5a5cccbb
classifier: demo-classifier
generated_at: 2026-05-04T00:00:00Z
---

## Why no demo

The diff adds structured log lines (`INFO`-level `log_event` calls) to internal service methods and a shared helper, plus 7 pin tests. No HTTP route decorators are added or changed, no React components are touched, no MCP tool schemas change, and no CLI output surface changes. The strongest `needs_demo` candidate was `src/gateway/app.py` (logger configuration in lifespan), but this is internal observability tuning with no effect on any HTTP response shape, request schema, or user-visible behaviour. The verdict would flip to `needs_demo` if the diff had added a new `@router.get` or `@router.post` decorator anywhere in `src/**`, or changed what any existing endpoint returns.

## Changed files

- src/agent/services.py
- src/gateway/app.py
- src/gateway/review_engine.py
- src/gateway/review_loop.py
- src/gateway/webhook_dispatcher.py
- src/shared/log_event.py
- tests/gateway/test_structured_logs.py
