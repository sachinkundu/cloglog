# Work Log — wt-t314-vendor-plugin-scripts

**Task:** T-314 — Phase 1.1: vendor cloglog scripts into plugins/cloglog/scripts/
**PR:** https://github.com/sachinkundu/cloglog/pull/241
**Merged:** 2026-04-27T08:32:30Z

## What Was Done

Vendored three cloglog-specific scripts into `plugins/cloglog/scripts/` to make the plugin self-contained for multi-project use:

1. **`plugins/cloglog/scripts/gh-app-token.py`** — parametrised copy; removed hardcoded cloglog App/Installation IDs, now reads `GH_APP_ID` / `GH_APP_INSTALLATION_ID` from env with clear error messages on missing vars.

2. **`plugins/cloglog/scripts/wait_for_agent_unregistered.py`** — copied as-is.

3. **`plugins/cloglog/scripts/install-dev-hooks.sh`** — copied as-is.

Updated skill citations across five SKILL.md files to use `${CLAUDE_PLUGIN_ROOT}/scripts/<name>` instead of project-relative paths:
- `plugins/cloglog/skills/github-bot/SKILL.md`
- `plugins/cloglog/skills/close-wave/SKILL.md`
- `plugins/cloglog/skills/reconcile/SKILL.md`
- `plugins/cloglog/skills/init/SKILL.md` (replaced `find ~/code` lookup with env-var export instructions)
- `plugins/cloglog/skills/setup/SKILL.md`

Added operator onboarding surfaces for the new env vars:
- `scripts/preflight.sh` — added warn block for missing `GH_APP_ID`/`GH_APP_INSTALLATION_ID`
- `docs/setup-credentials.md` — added T-314 subsection with export commands and direnv guidance

Added 10 pin/smoke tests in `tests/plugins/test_skills_use_plugin_root_scripts.py`:
- 3 absence pins (no bare path in skills)
- 3 presence pins (vendored scripts exist)
- 4 smoke tests (env-var contract: missing GH_APP_ID → error, missing INSTALLATION_ID → error, missing PEM → error, no hardcoded IDs in script)

Updated `tests/plugins/test_auto_merge_skill_handles_silent_holds.py` to pin `${CLAUDE_PLUGIN_ROOT}/scripts/auto_merge_gate.py` (existing test broke after replace_all).

## Codex Review Rounds

- **r1** — MEDIUM: `init/SKILL.md` used `.env` file for env vars (not auto-sourced). Fixed: replaced with shell export / shell RC instructions + direnv note.
- **r2** — MEDIUM: env vars not in onboarding/validation flow. Fixed: added `preflight.sh` warn block and `docs/setup-credentials.md` T-314 subsection. Exemption hash updated after each fix.
- **r3** — `:pass:`

## Test Results

- 966 passed, 1 xfailed
- CI: pass
- E2E: pass
