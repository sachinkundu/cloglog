# Wave t346 — work log

**Date:** 2026-04-29
**Wave:** wave-t346
**Worktrees in scope:** `wt-t346-project-patch-and-backfill`

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|---------------|-------|
| `wt-t346-project-patch-and-backfill` | [#270](https://github.com/sachinkundu/cloglog/pull/270) | cooperative (agent self-emitted `agent_unregistered` post-merge) | Launcher PID 650835/650830 lingered after `unregister_agent` — tab closed manually. See *Learnings* below. |

## What shipped (T-346)

— *Inlined from `wt-t346-project-patch-and-backfill/shutdown-artifacts/work-log-T-346.md`* —

`/cloglog init` re-runs now repair the cloglog backend's `Project.repo_url` from the local `git remote get-url origin` — closing the silent-failure chain that drops every webhook for a project with empty `repo_url` (`find_project_by_repo` does `repo_url.endswith(repo_full_name)` and returns `None` on empty). New `PATCH /api/v1/projects/{id}` route + `mcp__cloglog__update_project` MCP tool + Step 6a backfill in the init SKILL. Server-side canonicalization (`https://github.com/<owner>/<repo>`, `.git` stripped, SSH→HTTPS) on every write path.

### Files touched

- `src/board/repo_url.py` *(new)* — stdlib-only `normalize_repo_url` helper
- `src/board/schemas.py` — `ProjectUpdate` (name/description plain `str = ""`, `repo_url: str | None = None`)
- `src/board/repository.py` — `update_project` applies fields unconditionally
- `src/board/services.py` — `update_project` + `create_project` route through `normalize_repo_url`
- `src/board/routes.py` — `PATCH /projects/{project_id}` with `_: CurrentMcpOrDashboard` dep
- `mcp-server/src/server.ts` — `update_project` tool + `ensureProject()` lazy-resolves project_id via `GET /gateway/me`
- `mcp-server/src/client.ts` — `/gateway/me` routed with project API key + `X-MCP-Request: true`
- `mcp-server/src/tools.ts` + tests — handler + cases
- `plugins/cloglog/skills/init/SKILL.md` — Step 6a canonicalizes URL in shell + calls `mcp__cloglog__update_project`
- `tests/board/test_repo_url.py` *(new)* — 16 unit cases on the normalizer
- `tests/board/test_routes.py` — 9 new route cases
- `tests/plugins/test_init_repo_url_backfill.py` *(new)* — bash↔python parity pin
- `docs/contracts/baseline.openapi.yaml` + `frontend/src/api/generated-types.ts` — registered PATCH + `ProjectUpdate`
- `docs/demos/wt-t346-project-patch-and-backfill/{demo-script.sh,demo.md}`

### Decisions

- **Single canonicalization layer.** `src/board/repo_url.py::normalize_repo_url` is the only place URLs get rewritten; both `create_project` and `update_project` route through it. The init SKILL's Step 6a duplicates the transform in shell so init can compute the canonical URL pre-write — pin keeps them in lockstep.
- **`name`/`description` plain `str`, `repo_url` nullable.** Columns NOT NULL with `""` default. Plain `str = ""` makes the OpenAPI shape accurate; only `repo_url` keeps `str | None` (service coerces null → `""`).
- **Lazy `project_id` resolution for `update_project`.** `ensureProject()` lazy-fetches via `GET /api/v1/gateway/me` so init can call this tool before any worktree exists.

### Review (5 codex rounds, all caught real bugs)

| Round | Finding | Fix |
| --- | --- | --- |
| 1 | `ProjectUpdate.name`/`.description` nullable but columns NOT NULL → 500 | tightened to `str = ""` |
| 1 | PATCH route lacked per-route MCP guard | `_: CurrentMcpOrDashboard` dep added |
| 2 | `update_project` called pre-`register_agent` → "Not registered" | `ensureProject()` lazy-resolves |
| 3 | `/gateway/me` is `CurrentProject`-protected | client routed with project API key |
| 4a | OpenAPI advertised nullable but validator rejected | re-typed as plain `str = ""` |
| 4b | `/gateway/me` middleware path 1 still requires `X-MCP-Request: true` | header added |
| 5 | `:pass:` | merged via auto-merge gate |

## Learnings & Issues

Captured for CLAUDE.md (operator decision: candidate set extracted to per-task work log; folded into project CLAUDE.md if non-obvious):

- **`requireProject()` vs `ensureProject()` distinction in the MCP server.** Tools that operate on the project (`update_project`, anything called pre-registration) lazy-resolve via `GET /gateway/me`; tools that operate on a worktree session require prior `register_agent`. Conflating the two silently fails or 401s.
- **Middleware presence check ≠ per-route validation.** `ApiAccessControlMiddleware` only checks header presence; per-route deps validate bearer values. Any new MCP-proxied write that doesn't add the per-route dep accepts a garbage bearer + `X-MCP-Request: true`.
- **`/api/v1/gateway/me` shape** is project API key + `X-MCP-Request: true` together — both required by middleware path 1 + `CurrentProject` dep.
- **Pydantic `str | None = None` advertises `anyOf[string, null]` in OpenAPI even with a null-rejecting validator.** If the column is NOT NULL, type the field as plain `str = ""`.
- **Showboat `verify` re-runs every captured `exec` block in a clean shell with no live backend.** Use `uvx showboat note` for narrative + run live curl assertions in the demo-script.sh body.

### Wave-level integration issue

- **Launcher PID lingered after `unregister_agent`.** The wt-t346 launcher (PID 650830) and its child claude (650835) did not exit after the agent emitted `agent_unregistered`. Possible causes: post-merge `/clear`-then-relaunch race, or trap-on-EXIT not firing for clean child exit. Tab was closed manually during close-wave Step 6. Worth a backlog task — file under F-48 (Agent Lifecycle Hardening).

## State after this wave

- T-346 implementation merged: PATCH /projects + repo_url canonicalization + init backfill ship complete.
- MCP server tool surface advanced (added `update_project`); existing worktrees received `mcp_tools_updated` broadcast and may need restart per `plugins/cloglog/docs/agent-lifecycle.md` §6.
- T-348 + T-350 worktree agents are still running and unaffected (they don't use `update_project`).
- No follow-up tasks from T-346 itself; adjacent (T-285, T-343) explicitly out-of-scope.
