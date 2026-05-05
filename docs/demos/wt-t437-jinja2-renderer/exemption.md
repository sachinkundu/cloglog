---
verdict: no_demo
diff_hash: eba406adcea30d35c501a9bb1f328eaf8ef7e3186025fb06284f481ce52051d5
classifier: demo-classifier
generated_at: 2026-05-05T00:00:00Z
---

## Why no demo

Diff is confined to `plugins/cloglog/` template renderer
(`render_template.py` switched from `@@KEY@@` `str.replace` to Jinja2
`{{ key }}`), the two templates (`launch.sh.template`,
`task.md.template`), SKILL.md / docs prose updates, `pyproject.toml` /
`uv.lock` to add `jinja2`, and four test files under `tests/plugins/`.
No `src/**` routes, no `frontend/src/**`, no
`mcp-server/src/server.ts` tool registrations, no migrations. The
strongest needs_demo candidate was the `launch.sh.template` change
since it affects what agents execute, but the launch surface is
internal tooling for spawning agents — stakeholders never read its
stdout. If the diff had also altered an MCP tool schema in
`mcp-server/src/server.ts` or added a backend `@router` decorator in
`src/**`, the verdict would flip to `needs_demo`.

## Changed files

- plugins/cloglog/docs/launch-design.md
- plugins/cloglog/scripts/render_template.py
- plugins/cloglog/skills/launch/SKILL.md
- plugins/cloglog/templates/launch.sh.template
- plugins/cloglog/templates/task.md.template
- pyproject.toml
- tests/plugins/test_launch_sh_loads_plugin_live.py
- tests/plugins/test_launch_skill_per_project_credentials.py
- tests/plugins/test_launch_skill_renders_clean_launch_sh.py
- tests/plugins/test_launch_skill_renders_template_and_task_md.py
- uv.lock
