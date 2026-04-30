---
verdict: no_demo
diff_hash: 0094ffb97891906d007c0bd088e3cb5794ca4ab28c6a7be164c4df85f1d03746
classifier: demo-classifier
generated_at: 2026-04-30T00:00:00Z
---

## Why no demo

Diff is plugin-internal: launch SKILL.md, the new AGENT_PROMPT.md template,
CLAUDE.md learnings, `.gitignore` un-ignore for the template, plus pin tests
under `tests/plugins/` and two `tests/test_*.py` files. No `@router.*`
decorators, no `frontend/src` changes, no `server.tool(...)` edits in
`mcp-server/src/server.ts`, no CLI stdout changes, no migrations.

Strongest counter-signal considered was the AGENT_PROMPT.md template change,
but that's agent-instruction wording inside a worktree-private prompt file —
not a user-observable surface. If the diff had also added or modified an
`@router` in `src/**`, a `server.tool` registration, or React component
output on a routed page, the verdict would flip to `needs_demo`.

## Changed files

- .gitignore
- CLAUDE.md
- plugins/cloglog/skills/launch/SKILL.md
- plugins/cloglog/templates/AGENT_PROMPT.md
- tests/plugins/test_agent_prompt_template_correct_inbox_paths.py
- tests/plugins/test_agent_prompt_template_no_workflow_override_recurrence.py
- tests/plugins/test_launch_skill_renders_template_and_task_md.py
- tests/plugins/test_plugin_search_guidance.py
- tests/test_agent_lifecycle_pr_signals.py
- tests/test_mcp_failure_rule_wording.py
