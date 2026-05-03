---
verdict: no_demo
diff_hash: a463646a44cd90e91a06e9416e959cd84b120081886372a7d2f5aaedc781babd
classifier: demo-classifier
generated_at: 2026-05-03T00:00:00Z
---

## Why no demo

Diff is plugin/agent-lifecycle plumbing: a new PostToolUse hook
(`plugins/cloglog/hooks/exit-on-unregister.sh`) wired in
`plugins/cloglog/settings.json`, a pin test, and a close-wave SKILL.md
doc update. No HTTP route decorators, no React component changes, no
MCP `server.tool(...)` registrations, no CLI stdout surface change — it
only TERMs the local claude process after a successful unregister so
the launcher's `wait` returns. Strongest counter-signal considered was
the settings.json hook wiring, but it's internal supervisor plumbing
invisible at any user-facing boundary. If the diff had touched
`mcp-server/src/server.ts` tool schemas or added a backend route to
drive shutdown, I would have flipped to needs_demo.

## Changed files

- plugins/cloglog/hooks/exit-on-unregister.sh
- plugins/cloglog/settings.json
- plugins/cloglog/skills/close-wave/SKILL.md
- tests/test_exit_on_unregister_hook.py
