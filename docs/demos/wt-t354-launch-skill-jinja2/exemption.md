---
verdict: no_demo
diff_hash: 69f16d69f94913c719fe646a09f5ba840db53eb593fdd17cf0d34bd1d47728e5
classifier: demo-classifier
generated_at: 2026-05-05T00:00:00Z
---

## Why no demo

Plugin-internal refactor. A new helper `plugins/cloglog/scripts/render_template.py`
replaces the sed-escape pipeline embedded in
`plugins/cloglog/skills/launch/SKILL.md`, plus static templates
(`launch.sh.template`, `task.md.template`) and pin tests under
`tests/plugins/`.

**Signal:** no `@router.*` decorators, no `frontend/src/**` rendered output,
no `server.tool(...)` registrations in `mcp-server/src/server.ts`, no
user-read CLI/Makefile output, no migration.

**Counter-signal considered:** the new `launch.sh.template` changes what
`launch.sh` writes — but launch.sh is supervisor plumbing read by the
agent bootstrap, not a user-observable CLI surface. Its output is
internal.

**Counterfactual:** had the diff added or changed an HTTP route in
`src/**/routes.py`, a visible React component, or an MCP
`server.tool(...)` registration, this would flip to needs_demo.

## Changed files

- .gitignore
- plugins/cloglog/docs/launch-design.md
- plugins/cloglog/scripts/render_template.py
- plugins/cloglog/skills/launch/SKILL.md
- plugins/cloglog/templates/launch.sh.template
- plugins/cloglog/templates/task.md.template
- tests/plugins/test_launch_sh_loads_plugin_live.py
- tests/plugins/test_launch_skill_exports_gh_app_env.py
- tests/plugins/test_launch_skill_model_selection.py
- tests/plugins/test_launch_skill_per_project_credentials.py
- tests/plugins/test_launch_skill_renders_clean_launch_sh.py
- tests/plugins/test_launch_skill_renders_template_and_task_md.py
- tests/plugins/test_launch_skill_uses_abs_paths.py
- tests/plugins/test_no_python_yaml_in_scalar_hooks.py
