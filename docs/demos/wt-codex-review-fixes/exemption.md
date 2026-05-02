---
verdict: no_demo
diff_hash: a36333c88ff45abacc751acc172b16ef4fdd597cd58d2fc4f24dd8e774c06db8
classifier: demo-classifier
generated_at: 2026-05-02T20:40:00Z
---

## Why no demo

Diff is internal plumbing in the gateway review engine: scales the codex subprocess timeout by diff size (compute_review_timeout), threads the budget through _run_agent_once/CodexReviewer.run, and emits a codex_review_timed_out inbox event for the owning agent. No HTTP route decorators changed, no React/UI surface, no MCP tool schemas, no CLI output, no migrations — just timeout tuning, logging fields, and an internal inbox event consumed by agents. Strongest needs_demo candidate considered: the new inbox event payload, but agent-inbox JSONL is an internal cross-context channel, not a stakeholder-observable surface. Counterfactual: had the change altered a webhook HTTP endpoint, added a new MCP tool, or changed PR comment copy that stakeholders read on the dashboard route, I would have flipped to needs_demo.

## Changed files

- src/gateway/review_engine.py
- src/gateway/review_loop.py
- src/gateway/webhook_consumers.py
- tests/gateway/test_review_engine.py
