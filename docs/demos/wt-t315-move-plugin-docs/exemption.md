---
verdict: no_demo
diff_hash: 5249bd994f084758ff62e8ad958583ca3005419d37ff78bd13c651eed120b647
classifier: demo-classifier
generated_at: 2026-04-28T07:30:10Z
---

## Why no demo

All changed files are documentation (docs/design/*.md, plugins/cloglog/docs/*.md, SKILL.md files, templates, and agents) plus path-reference updates in hooks and scripts that replace bare `docs/design/agent-lifecycle.md` with the plugin-relative path `plugins/cloglog/docs/agent-lifecycle.md`. No HTTP routes, React components, MCP tool schemas, or CLI output surfaces were changed. A new test file pins the new doc structure. The hook changes only update comment/error-message strings pointing to the doc path — no behavioral logic changed.

## Changed files

- docs/design/agent-lifecycle.md
- docs/design/two-stage-pr-review.md
- docs/setup-credentials.md
- plugins/cloglog/agents/worktree-agent.md
- plugins/cloglog/docs/agent-lifecycle.md
- plugins/cloglog/docs/setup-credentials.md
- plugins/cloglog/docs/two-stage-pr-review.md
- plugins/cloglog/hooks/agent-shutdown.sh
- plugins/cloglog/hooks/prefer-mcp.sh
- plugins/cloglog/scripts/wait_for_agent_unregistered.py
- plugins/cloglog/skills/close-wave/SKILL.md
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/init/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- plugins/cloglog/skills/reconcile/SKILL.md
- plugins/cloglog/skills/setup/SKILL.md
- plugins/cloglog/templates/claude-md-fragment.md
- tests/plugins/test_plugin_docs_self_contained.py
