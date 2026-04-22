# F-48 Wave D work log — 2026-04-22

Wave D of the F-48 Agent Lifecycle Hardening feature. Two parallel agents; two PRs; both merged.

## Worktrees

### wt-d1-shutdown-mcp — PR #178

**Title:** feat(agent-lifecycle): T-218 + T-221 — request_shutdown + force_unregister MCP tools
**Tasks:** T-218 (add `request_shutdown` MCP tool) and T-221 (admin force-unregister endpoint + MCP tool), shipped as one bundled PR per the Wave D plan.
**Merged:** 2026-04-21 08:54Z

Commits:
- `5883f6b` — feat(agent-lifecycle): T-218 + T-221 — request_shutdown + force_unregister MCP tools
- `21216f9` — fix(agent-lifecycle): codex round 1 — request_shutdown auth + demo source paths

Files changed (17):
- Backend: `src/agent/{routes,schemas,services}.py`, `src/gateway/auth.py`, `tests/agent/test_integration.py`
- MCP server: `mcp-server/src/{client,server,tools}.ts`, `mcp-server/src/__tests__/tools.test.ts`, `mcp-server/tests/{client,server}.test.ts`
- Contract: `docs/contracts/baseline.openapi.yaml`
- Demo: `docs/demos/wt-d1-shutdown-mcp/{demo,demo-script.sh}`

### wt-d2-close-off-template — PR #179

**Title:** feat(board): auto-file close-off task when worktree is created (T-246)
**Tasks:** T-246 (template close-off task auto-created with each worktree).
**Merged:** 2026-04-22 04:33Z

Commits:
- `3a9002c` — feat(board): auto-file close-off task when a worktree is created
- `06b5901` — test: stop using id(object()) for project names in dep fixture (Boy Scout)

Files changed (10 net new/modified, excluding D1 overlap):
- Backend: `src/board/{models,repository,schemas,services,templates}.py`, `src/agent/routes.py`
- Migration: `src/alembic/versions/d2a1b3c4e5f6_add_close_off_worktree_id_to_tasks.py`
- MCP server: `mcp-server/src/{client,server,tools}.ts`
- Hook: `.cloglog/on-worktree-create.sh`
- Contract: `docs/contracts/d2-close-off-template.openapi.yaml`
- Tests: `tests/agent/test_close_off_task.py` (new), `tests/board/test_dependencies.py` (Boy-Scout fix)
- Demo: `docs/demos/wt-d2-close-off-template/{demo,demo-script.sh}`

## Learnings & Issues

### Codex findings on PR #178 (shutdown MCP tools)

1. **[MEDIUM] `request_shutdown` route had no per-route auth dep.** The `/api/v1/agents/*` gateway middleware only gates on Bearer *presence*; any Bearer value reached the handler before the fix. Fixed by depending on `SupervisorAuth` + adding 401/403 regression tests. Now pinned in CLAUDE.md under *Cross-Context Integration* so future agent endpoints can't ship open.
2. **[HIGH] Demo script grepped `mcp-server/dist/*.js`.** `scripts/run-demo.sh` never builds the MCP server; on a fresh clone with no `dist/`, `set -euo pipefail` killed the first grep before any proof was recorded. Fixed by pointing demos at `src/*.ts`. Now pinned in CLAUDE.md under *Proof-of-Work Demos*.

### Codex findings on PR #179 (close-off task template)

1. **[HIGH] `_resolve_backend_url` in `.cloglog/on-worktree-create.sh` uses `python3 -c 'import yaml'`.** On hosts without global PyYAML, silently falls back to `http://localhost:8000`. Merged without the fix (codex bot went into two crashed-review rounds first, then surfaced this on round 3 after the user's round). Tracked as **T-259** (expedite) with the verified grep+sed diff ready to apply. Also pinned in CLAUDE.md under *Environment Quirks* (precedent comment in `agent-shutdown.sh:64-68` existed but didn't stop the regression).
2. **[MEDIUM false positive] Codex flagged `McpOrProject` as a missing import.** Confirmed by D2 agent that codex was reading against `/home/sachin/code/cloglog-prod/` which hadn't picked up D1 yet. T-255 already tracks the review-engine source-root hazard.

### Non-review learnings worth carrying forward

- **`showboat verify` line-number fragility on rebase.** Any `grep -n` in a demo captures line numbers; rebasing shifts them and `showboat verify` byte-mismatches. D2 regenerated the demo after the D1 rebase. Workarounds: drop `:N:` line prefixes from captures, or re-run `make demo` post-rebase. Consider adding to `plugins/cloglog/skills/demo/SKILL.md` Determinism section.
- **Worktree rebase checklist when a sibling merges first.** D2 had to rebase onto D1, re-run migrations, rebuild `mcp-server/dist/`, **and** regenerate the demo (step often missed). D2's shutdown learnings captured this as a 6-step checklist.
- **Stop using `id(object())` for test project names.** CPython reuses addresses after GC; under certain orderings the same `id()` re-appears and hits `projects_name_key` UniqueViolation. D2 Boy-Scouted `tests/board/test_dependencies.py` to use `uuid4().hex[:12]`. Grep-worthy follow-up: `grep -rn "id(object())" tests/` — any remaining hits should get the same fix.

### Follow-up tasks filed this wave
- **T-259 (expedite)** — Fix `_resolve_backend_url` PyYAML regression in `.cloglog/on-worktree-create.sh`.
- **T-260** — Surface codex review progress on task/PR card ("codex reviewing" badge + state machine).

### Pre-existing T-232 updated
Appended a concrete motivation section to T-232 (Structured JSON logging): every log line across backend, MCP server, and hook scripts MUST carry an ISO-8601 UTC timestamp. Names the current offenders (`/tmp/agent-shutdown-debug.log`, hook scripts, gunicorn stdout, MCP stderr) and pins "ts on every line" as a correctness requirement.

## State after this wave

**F-48 progress (after Wave D):**

| Wave | Tasks | Status |
|---|---|---|
| A — spec | T-222 | done |
| B — foundations | T-215, T-217, T-219, T-242, T-214 | done |
| C — plugin docs + MCP rebuild | T-216, T-243, T-244 | done |
| **D — shutdown MCP tools + close-off template** | **T-218, T-221, T-246** | **done (this wave)** |
| E — capstone | T-220 (reconcile + close-wave rewrite) | ready to launch |

**Backlog added this wave:** T-259 (PyYAML hook regression — expedite), T-260 (codex review progress badge).

**New runtime surface on main:**
- Backend: `POST /api/v1/agents/{worktree_id}/force-unregister` (project/MCP auth, idempotent, emits `WORKTREE_OFFLINE(reason=force_unregistered)`), `POST /api/v1/agents/close-off-task` (project auth, idempotent by `close_off_worktree_id` UNIQUE column).
- MCP tools: `request_shutdown`, `force_unregister`, `create_close_off_task`. Surface broadcast via `mcp_tools_updated` event from `make sync-mcp-dist` on close-wave.
- Schema: tasks gain a nullable `close_off_worktree_id` FK column (migration `d2a1b3c4e5f6`).
- Hook: `.cloglog/on-worktree-create.sh` POSTs to the close-off-task endpoint after bootstrap (currently partially broken on hosts without global PyYAML — T-259).

**Wave E readiness:** T-220 can now be launched — it consumes `request_shutdown` (D1), `force_unregister` (D1), `agent_unregistered` event (Wave C), and rewrites `plugins/cloglog/skills/reconcile/SKILL.md` + `plugins/cloglog/skills/close-wave/SKILL.md` to use the three-tier cooperative shutdown protocol documented in `plugins/cloglog/templates/claude-md-fragment.md:55`.
