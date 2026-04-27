---
verdict: no_demo
diff_hash: e3480d943c261274cbaabbdd1c0388a3f9434efbd88df08a3cf1fee7b78f7b57
classifier: demo-classifier
generated_at: 2026-04-27T11:00:00Z
---

## Why no demo

Signal: all changed files are plugin skill/agent/template docs, design docs, MCP server hint text, and test files. No user-observable behaviour changed — the one-task-per-session contract is an internal agent lifecycle rule that only affects autonomous worktree agent sessions, not end-user API surfaces, UI components, or CLI output.

Counter-signal: `mcp-server/src/server.ts` is not on the static allowlist. However the change is a hint string in the `update_task_status` response explaining shutdown ordering — it does not alter the tool's parameters, response schema, or any externally observable behaviour.

Counterfactual: a stakeholder watching the Kanban dashboard or calling the REST API would observe identical behaviour before and after this PR. The change is purely operational guidance for autonomous agents running inside the system.

## Changed files

- docs/design/agent-lifecycle.md
- mcp-server/src/server.ts
- plugins/cloglog/agents/worktree-agent.md
- plugins/cloglog/skills/close-wave/SKILL.md
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- plugins/cloglog/skills/setup/SKILL.md
- plugins/cloglog/templates/claude-md-fragment.md
- tests/plugins/test_per_task_work_log_schema.py
- tests/plugins/test_worktree_agent_one_task_per_session.py
