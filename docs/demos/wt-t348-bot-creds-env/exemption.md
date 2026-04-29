---
verdict: no_demo
diff_hash: 0bb7e1fb362e044001554a1a5d3053053783cf0525b3bd6ec266821d0f87216a
classifier: demo-classifier
generated_at: 2026-04-29T00:00:00Z
---

## Why no demo

Diff touches only operator-host bot-credential plumbing: gh-app-token.py adds env→local.yaml→config.yaml resolution, launch.sh exports GH_APP_ID/INSTALLATION_ID into worktree shells, preflight.sh adds yaml fallback checks, and SKILL.md/docs/.gitignore document the new local.yaml path. No HTTP route decorators, no React component changes, no MCP tool registrations, no user-facing CLI output changes — gh-app-token.py is internal to bot auth, not a CLI surface a user reads. Strongest needs_demo candidate was the gh-app-token.py error-message change ('GH_APP_ID is required (env or .cloglog/local.yaml)'), but that's a misconfiguration error path for plugin internals, not a user-observable CLI output. Counterfactual: if the diff had added a new @router decorator under src/**, modified an mcp-server/src/server.ts tool registration, or changed UI copy on a routed React page, verdict would flip to needs_demo.

## Changed files

- .cloglog/config.yaml
- .gitignore
- CLAUDE.md
- README.md
- docs/setup-credentials.md
- plugins/cloglog/docs/setup-credentials.md
- plugins/cloglog/scripts/gh-app-token.py
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/init/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- scripts/preflight.sh
- tests/plugins/test_launch_skill_exports_gh_app_env.py
