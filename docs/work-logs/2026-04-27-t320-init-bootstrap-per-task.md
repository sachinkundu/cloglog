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

Also fixed the default backend URL from `:8000` to `127.0.0.1:8001` throughout.

## Files Changed

- `plugins/cloglog/skills/init/SKILL.md` — Step 2 completely replaced; Step 1c URL fixed; Step 3/4a templates updated for detected BACKEND_URL
- `docs/setup-credentials.md` — Two-phase init docs; single-slot warning updated; manual bootstrap section with backend_url write and multi-project conditional
- `tests/plugins/test_init_bootstrap_skill.py` — 10 new pin tests (all passing)

## Key Design Decisions

1. **Repo-scoped skip condition**: Phase 1 uses `project_id` in `.cloglog/config.yaml` (not `~/.cloglog/credentials`) as the "already bootstrapped" signal — credentials is a global file and would reuse project A's key when initializing project B.
2. **Dual skip check**: Must have BOTH `project_id` AND credentials before skipping Phase 2 — a cloned repo (project_id present but no local credentials) must go through the repair path.
3. **MULTI_PROJECT branch**: Instead of hard-stopping when credentials already exist, proceed with project creation but print the key for `export CLOGLOG_API_KEY=<key>` rather than overwriting the file.
4. **backend_url persistence**: Phase 2 writes `backend_url` to config so hooks (worktree-create.sh, agent-shutdown.sh) don't fall back to `localhost:8000` after restart.
5. **Canonical YAML parser**: Used `grep | head -n1 | sed strip-prefix | sed strip-comments | tr -d quotes` to match `plugins/cloglog/hooks/lib/parse-yaml-scalar.sh`.

## Codex Review History

6 rounds of review across 5 sessions (sessions 4 and 5 each triggered twice due to intermediate commits):
- **Session 1**: Wrong endpoint (`/api/v1/board/projects`→`/api/v1/projects`), wrong env var (`CLOGLOG_DASHBOARD_KEY`→`DASHBOARD_SECRET`), wrong skip condition (credentials file→project_id)
- **Session 2**: `localhost`→`127.0.0.1`, project_id alone insufficient (need creds check too)
- **Session 3**: backend_url not persisted across restart, weaker YAML parser, single-slot guard
- **Session 4**: `CLOGLOG_DASHBOARD_KEY` still in single-slot message, manual bootstrap missing backend_url write
- **Session 5**: Hard-stop guard before project creation makes multi-project path impossible; manual section unconditionally overwrites credentials

## Residual TODOs / context the next task should know

- **Multi-project credential format is still a gap** (`docs/design/plugin-portability-audit.md:421-426`). The MULTI_PROJECT branch is a workaround — the operator exports the key manually. A proper per-project credentials file (e.g., `~/.cloglog/<project-id>/credentials`) would be cleaner and is tracked as follow-up in the portability audit.
- The `test_step2_writes_credentials_file` pin test asserts `~/.cloglog/credentials` appears in Step 2 — it does (in the `if [ "$MULTI_PROJECT" = "false" ]` branch). The conditional doesn't break the pin because the string still appears in the file.
- `docs/setup-credentials.md` manual bootstrap section now has a multi-project conditional inline in the bash snippet. This is more complex than ideal; a future refactor could extract it to a helper script.
- Pin tests are absence-based for the MCP call (`mcp__cloglog__get_board`) and presence-based for the new path. This is the correct polarity — see CLAUDE.md "Presence-pins survive narrowing; absence-pins catch returns."
