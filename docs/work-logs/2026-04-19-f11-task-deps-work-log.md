# Work Log — wt-task-deps (F-11 Feature Dependency Enforcement + F-48 dogfood)

**Date:** 2026-04-19
**Worktree:** wt-task-deps
**Agent tasks:** 5 (all complete from the agent's side — T-225 landed in `review` with PR merged; the administrative move to `done` is the user's.)

## Tasks shipped

| # | Task | Type | PR | Status |
|---|------|------|----|--------|
| 1 | T-223 — Spec: unified dependency checks at task start (feature-level + task-level) | spec | #146 | done |
| 2 | T-226 — Plan: implementation plan for F-11 dependency checks | plan | #147 | done |
| 3 | T-36 — Feature-level dependency guard at `start_task` (F-11 PR A) | task | #148 | done |
| 4 | T-224 — Task-level dependencies: backend + MCP tools + `start_task` guard (F-11 PR B) | impl | #149 | done |
| 5 | T-225 — Dogfood: encode F-48 internal ordering via `add_task_dependency` | task | #150 | review (pr_merged=true) |

Each task went through spec/plan pipeline → implementation → `make quality` → codex review → merge. Two tasks required codex-review revisions (T-223 rounds 1 and 2; T-226 rounds 1 and 2).

## PRs

- **#146** — `docs(spec): T-223 unified task+feature dependency checks at start_task` (plus two follow-ups for codex rounds 1 & 2).
- **#147** — `docs(plan): T-226 implementation plan for F-11 dependency checks` (plus two follow-ups for codex rounds 1 & 2).
- **#148** — `feat(agent,board): T-36 feature-level dependency guard at start_task (F-11 PR A)` — includes retrofit of `CurrentMcpOrDashboard` onto feature-dep routes and a frontend fix for `removeDependency` sending the dashboard key.
- **#149** — `feat(board): T-224 task-level dependencies (F-11 PR B)` — migration, `task_dependencies` table, routes, MCP tools, cycle detection, `start_task` + `update_task_status` guards, integration tests across three layers. Trailing commit: `docs(contract): add task-dep routes to baseline OpenAPI`.
- **#150** — `docs(f-48): T-225 dogfood task-level deps on F-48 ordering` — nine `add_task_dependency` calls; demo doc at `docs/demos/wt-task-deps/t225-dogfood.md`. Codex review returned `:pass:`.

## F-48 graph encoded (T-225)

Nine `blockedBy` edges committed via `mcp__cloglog__add_task_dependency`:

```
T-222 (canonical lifecycle doc, spec)
  ├── T-213   (broaden Stop on MCP failure rule)
  ├── T-214   (stop exposing CLOGLOG_API_KEY)
  ├── T-215   (unify inbox path backend)
  │     ├── T-216  (sync plugin docs to unified inbox path)
  │     └── T-218  (request_shutdown MCP tool)
  │            └── T-220  (rewrite reconcile + close-wave skills)
  ├── T-217   (fix SessionEnd shutdown hook)
  └── T-219   (harden prefer-mcp.sh)

T-221 (admin force-unregister) ──── also blocks T-220
```

## Quality gates

- `make quality` passed on every PR before merge (lint, mypy, 557 backend tests, ~90.7% coverage, contract check, demo gate).
- Codex reviewer ran on every PR; comments were either addressed or pass-approved before merge.

## Migration chain

T-224 added a single Alembic migration (`task_dependencies` table). `down_revision` was rebased against the latest on main before PR #149 push.

## Notable cross-context touches

- `docs/contracts/baseline.openapi.yaml` extended with the two new task-dep routes (`POST /tasks/{id}/dependencies`, `DELETE /tasks/{id}/dependencies/{depends_on_id}`).
- `mcp-server/src/tools.ts` + `mcp-server/src/server.ts` gained `add_task_dependency` and `remove_task_dependency`; dist rebuilt before PR #149.
- `src/agent/routes.py` and `src/agent/services.py` extended to surface task-level blockers in `start_task` 409 payload alongside the feature-level ones introduced in T-36.

## Follow-ups for main

None that this agent is responsible for. T-225's review→done transition is an administrative move the user performs on the board.
