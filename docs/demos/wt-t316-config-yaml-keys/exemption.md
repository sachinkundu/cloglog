---
verdict: no_demo
diff_hash: 81016e10bd61f1255b93dfa59f68d72351fe4b151f771bb7707b4d006bd4dcd2
classifier: demo-classifier
generated_at: 2026-04-28T00:00:00Z
---

## Why no demo

**Signal**: pure portability refactor. Five hard-coded cloglog-specific
strings (`cloglog-codex-reviewer[bot]`, `cloglog-opencode-reviewer[bot]`,
`cloglog-dashboard-dev`, `cloglog-webhooks`, `cloglog-prod`, plus the
`demo_allowlist_paths` regex) move from plugin call sites into
`.cloglog/config.yaml`. Every consumer now reads from config; the cloglog
defaults preserve current behaviour exactly.

**Counter-signal**: none observable to a stakeholder. No HTTP route
decorators added or changed. No frontend changes. No MCP tool surface
changes. The auto-merge gate's CLI shape (JSON-in / reason-out) is
unchanged — only its source for the reviewer-bot list moved from a
module constant to a config-yaml lookup, behind the same external
interface.

**Counterfactual**: a stakeholder running `make dev`, calling the API,
or reviewing a PR sees identical behaviour before and after. The only
observable change is operator-side: editing `.cloglog/config.yaml` now
updates these values instead of editing skill prose / scripts.

## Changed files

- .cloglog/config.yaml
- plugins/cloglog/scripts/auto_merge_gate.py
- plugins/cloglog/skills/close-wave/SKILL.md
- plugins/cloglog/skills/demo/SKILL.md
- plugins/cloglog/skills/github-bot/SKILL.md
- plugins/cloglog/skills/launch/SKILL.md
- scripts/check-demo.sh
- scripts/preflight.sh
- tests/plugins/test_t316_no_hardcoded_literals.py
- tests/test_auto_merge_gate.py
- tests/test_check_demo_allowlist.py
- tests/test_check_demo_exemption_hash.py
