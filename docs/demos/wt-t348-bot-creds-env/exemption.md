---
verdict: no_demo
diff_hash: 9677c0728fe522b02afe2cd756e32bbfefd724852db0a2de3ecf0f85bd2f0c4a
classifier: demo-classifier
generated_at: 2026-04-29T00:00:00Z
---

## Why no demo

Diff is plumbing/docs-only: config.yaml gains non-secret gh_app_id/installation_id keys, launch SKILL.md heredoc adds _gh_app_id/_gh_app_installation_id readers and exports them in the generated launch.sh, preflight.sh widens its check, and README/setup-credentials/init SKILL.md update guidance. Strongest needs_demo candidate considered: scripts/preflight.sh user-facing CLI output changed — but preflight is a dev/CI sanity check, not a user-read CLI surface, and the change is just the wording of an existing warn/ok line. No HTTP route decorators, no React components, no MCP tool registrations, no migrations. Counterfactual: if this PR had also changed gh-app-token.py's stdout shape that github-bot skill users read, or added a new mcp__cloglog__ tool around bot-token minting, I would have flipped to needs_demo.

## Changed files

- .cloglog/config.yaml
- CLAUDE.md
- README.md
- docs/setup-credentials.md
- plugins/cloglog/docs/setup-credentials.md
- plugins/cloglog/skills/init/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- scripts/preflight.sh
- tests/plugins/test_launch_skill_exports_gh_app_env.py
