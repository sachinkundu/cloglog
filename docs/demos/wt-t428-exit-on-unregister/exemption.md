---
verdict: no_demo
diff_hash: f73da8bc9859b46943d05f6a56bd79489519d235dc0a5a46165e435dd7d3e868
classifier: demo-classifier
generated_at: 2026-05-05T00:00:00Z
---

## Why no demo

Diff touches only plugin internals: a hook script
(`plugins/cloglog/hooks/exit-on-unregister.sh`), a launcher template
(`plugins/cloglog/templates/launch.sh.template`), `.gitignore`, and a pin
test (`tests/test_exit_on_unregister_hook.py`). No HTTP routes, no React
components, no MCP tool definitions, no CLI stdout surface, no DB
migration. Strongest needs_demo candidate was the launcher template
change, but it only writes a runtime PID file consumed by the hook —
invisible to users. Counterfactual: if the change had altered claude's
startup banner, added a user-visible CLI flag, or modified an MCP tool
registration in `mcp-server/src/server.ts`, this would flip to
needs_demo.

## Changed files

- .gitignore
- plugins/cloglog/hooks/exit-on-unregister.sh
- plugins/cloglog/templates/launch.sh.template
- tests/test_exit_on_unregister_hook.py
