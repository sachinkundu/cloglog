---
verdict: no_demo
diff_hash: b89c0b39126c48da81eae388a10d2098f8744971fa7e59470efba5c4aa18f0d1
classifier: demo-classifier
generated_at: 2026-04-27T08:10:56Z
---

## Why no demo

The diff touches only plugin scripts (plugins/cloglog/scripts/gh-app-token.py, install-dev-hooks.sh, wait_for_agent_unregistered.py), skill documentation (plugins/cloglog/skills/*/SKILL.md), and pin tests (tests/plugins/). All changes are internal plumbing: vendoring scripts into the plugin tree and updating skill prose to reference them via `${CLAUDE_PLUGIN_ROOT}/scripts/` instead of project-relative paths. No HTTP route decorators are added or changed, no React components are affected, no MCP tool definitions are modified, and no CLI output surface changes. Counterfactual: if any skill changes had introduced a new @router.get or server.tool() registration, or if the CLI output of a user-invoked script had changed, the verdict would flip to needs_demo.

## Changed files

- plugins/cloglog/scripts/gh-app-token.py
- plugins/cloglog/scripts/install-dev-hooks.sh
- plugins/cloglog/scripts/wait_for_agent_unregistered.py
- plugins/cloglog/skills/close-wave/SKILL.md
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/init/SKILL.md
- plugins/cloglog/skills/reconcile/SKILL.md
- plugins/cloglog/skills/setup/SKILL.md
- tests/plugins/test_auto_merge_skill_handles_silent_holds.py
- tests/plugins/test_skills_use_plugin_root_scripts.py
