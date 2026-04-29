---
verdict: no_demo
diff_hash: f84a8e56bfd6563a9a14396b0a281e264c91b6989d1bd36423f362c0f4f50fd7
classifier: demo-classifier
generated_at: 2026-04-29T00:00:00Z
---

## Why no demo

Diff is plugin/config plumbing only: adds `gh_app_id`/`gh_app_installation_id` scalars to `.cloglog/config.yaml`, teaches the launch SKILL.md heredoc to read them via grep+sed and export them in `launch.sh` before `claude` runs, updates `scripts/preflight.sh` to accept either env or config, doc updates in init/setup-credentials SKILL.md and CLAUDE.md, and adds pin test `tests/plugins/test_launch_skill_exports_gh_app_env.py`. No HTTP route decorators in `src/**`, no React/UI changes, no MCP `server.tool(...)` registrations, no user-read CLI stdout change, no DB migrations. The strongest needs_demo candidate was `scripts/preflight.sh` (CLI output reword), but preflight is a developer/CI check whose output is not the primary user-observable surface and the change is a warning-text rewording — internal plumbing. Counterfactual: if the diff had added a `@router.*` in `src/**`, changed an MCP tool schema in `mcp-server/src/server.ts`, or touched a frontend routed component, this would flip to needs_demo.

## Changed files

- .cloglog/config.yaml
- CLAUDE.md
- plugins/cloglog/docs/setup-credentials.md
- plugins/cloglog/skills/init/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- scripts/preflight.sh
- tests/plugins/test_launch_skill_exports_gh_app_env.py
