---
verdict: no_demo
diff_hash: dc78abe8523be74715e413503704a4e1aca94497b222e7e214eb78a42361a151
classifier: demo-classifier
generated_at: 2026-04-26T11:26:35Z
---

## Why no demo

The diff is internal agent-workflow plumbing: docs
(`docs/design/agent-lifecycle.md` §3.1), plugin prompts
(`plugins/cloglog/agents/worktree-agent.md`,
`plugins/cloglog/skills/{github-bot,launch}/SKILL.md`), a pure-decision
helper (`plugins/cloglog/scripts/auto_merge_gate.py`), and pin tests. No
`@router.*` decorator changes anywhere under `src/**`, no
`frontend/src/**` edits, no `server.tool(...)` change in
`mcp-server/src/server.ts`, and the new script is invoked by worktree agents
(not a user-read CLI). The strongest `needs_demo` candidate was the
`auto_merge_gate.py` script, but it's an internal subprocess in an agent
handler — its stdout (`merge`/hold reason) is consumed by bash, not read by
a stakeholder. Counterfactual: if the change had also added a `@router.*`
endpoint to surface auto-merge state on the dashboard, or a UI badge in
`frontend/src/**` showing the `hold-merge` label state, the verdict would
have flipped to `needs_demo` (frontend-screenshot).

## Changed files

- docs/demos/wt-t295-auto-merge/exemption.md
- docs/design/agent-lifecycle.md
- plugins/cloglog/agents/worktree-agent.md
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- tests/plugins/test_auto_merge_skill_handles_silent_holds.py
- tests/test_auto_merge_gate.py
