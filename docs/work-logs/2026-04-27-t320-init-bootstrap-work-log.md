# Work Log — wt-t320-init-bootstrap

Worktree: /home/sachin/code/cloglog/.claude/worktrees/wt-t320-init-bootstrap
Session closed: 2026-04-27

---

<!-- T-320 -->
---
task: T-320
task_id: a7927551-0a0f-41fa-ad21-4bd1e5cdbb3e
title: "Phase 2.7: replace init Step 2 mcp__cloglog__get_board with admin/backend bootstrap"
pr: https://github.com/sachinkundu/cloglog/pull/245
pr_number: 245
branch: wt-t320-init-bootstrap
worktree: /home/sachin/code/cloglog/.claude/worktrees/wt-t320-init-bootstrap
status: merged
commits:
  - d90c021  # fix: wrong endpoint, env var, skip condition (session 1)
  - d336383  # fix: localhost→127.0.0.1, dual check for credentials (session 2)
  - 0065194  # fix: backend_url persistence, canonical YAML parser, single-slot guard (session 3)
  - 6f9636c  # fix: CLOGLOG_DASHBOARD_KEY→DASHBOARD_SECRET, manual bootstrap backend_url (session 4)
  - 9ac6658  # fix: exit-1→MULTI_PROJECT branch for multi-project machines (session 5)
---

## What Was Done

Replaced `mcp__cloglog__get_board` in the `init` skill's Step 2 with a direct HTTP bootstrap that works on fresh projects where the MCP server isn't yet configured. Implemented a two-phase init flow:

- **Phase 1 (pre-MCP):** calls `POST /api/v1/projects` with `X-Dashboard-Key: $DASHBOARD_SECRET`, writes `CLOGLOG_API_KEY` to `~/.cloglog/credentials` (or prints it for export on multi-project machines), writes `project_id` + `backend_url` to `.cloglog/config.yaml`, requests restart.
- **Phase 2 (post-restart):** MCP server finds credentials and existing `project_id`; bootstrap is skipped; remaining setup steps proceed via MCP tools.

Init/bootstrap now seeds `backend_url: http://127.0.0.1:8001` in `.cloglog/config.yaml`; other hooks (`worktree-create.sh`, `agent-shutdown.sh`, `enforce-task-transitions.sh`) and the launch.sh template still retain `localhost:8000` as their fallback when config is missing.

## Files Changed

- `plugins/cloglog/skills/init/SKILL.md` — Step 2 completely replaced; Step 1c URL fixed; Step 3/4a templates updated for detected BACKEND_URL
- `docs/setup-credentials.md` — Two-phase init docs; single-slot warning updated; manual bootstrap section with backend_url write and multi-project conditional
- `tests/plugins/test_init_bootstrap_skill.py` — 10 new pin tests (all passing)

## Residual TODOs / context the next task should know

- **Multi-project credential format is still a gap** (`docs/design/plugin-portability-audit.md:421-426`). The MULTI_PROJECT branch is a workaround — the operator exports the key manually. A proper per-project credentials file (e.g., `~/.cloglog/<project-id>/credentials`) would be cleaner and is tracked as follow-up in the portability audit.
- The conditional multi-project branch in the manual bootstrap snippet in `docs/setup-credentials.md` is more complex than ideal; a future refactor could extract it to a helper script.
- Pin tests are absence-based for the MCP call and presence-based for the new path — correct polarity per CLAUDE.md guidance.
