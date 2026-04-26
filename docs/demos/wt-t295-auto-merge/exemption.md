---
verdict: no_demo
diff_hash: 59af68c61bf54699805cd8c6f655fbc67d1143ee73a7bcedbe162f01ffa014b9
classifier: demo-classifier
generated_at: 2026-04-26T10:14:28Z
---

## Why no demo

Diff is internal agent-workflow plumbing: a new pure-Python decision helper at
`plugins/cloglog/scripts/auto_merge_gate.py`, prose updates to
`docs/design/agent-lifecycle.md` and two `plugins/cloglog/skills/*/SKILL.md`
files, plus pin tests under `tests/`. No `@router.*` decorators in
`src/**`, no `frontend/src/**` changes, no `server.tool` registrations in
`mcp-server/src/server.ts`, no `src/**/cli.py` or Makefile output-surface
changes, and no migrations. The strongest `needs_demo` candidate was the
`auto_merge_gate.py` helper, but it is invoked only by the worktree agent's
skill — not a user-facing CLI/route — so it doesn't clear the bar.
Counterfactual: if the diff had wired the helper into a user-invoked `make`
target or added a Gateway route exposing the gate decision, it would have
flipped to `needs_demo`.

## Changed files

- docs/demos/wt-t295-auto-merge/exemption.md
- docs/design/agent-lifecycle.md
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/plugins/test_auto_merge_skill_handles_silent_holds.py
- tests/test_auto_merge_gate.py
