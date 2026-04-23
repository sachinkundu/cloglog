# Work Log — F-48 Wave F (Agent Lifecycle Hardening)

**Close date:** 2026-04-23
**Wave:** wt-f48-wave-f (single agent, four sequential PRs)
**Tasks closed:** T-259, T-257, T-256, T-258

## Shutdown summary

| Worktree | PRs | Shutdown path | Commits | Notes |
|----------|-----|---------------|---------|-------|
| wt-f48-wave-f | #186, #188, #189, #191 | cooperative (agent self-unregistered 2026-04-23T10:23:53+03:00) | 7 on final branch tip + 4 merge commits on main | Agent consumed its own pr_merged events, cleanly advanced through all four tasks without supervisor intervention. Only cross-agent coordination was T-258's `mcp_tool_error` (`cross_agent_file_conflict` on `src/gateway/app.py` vs PR #187), resolved by supervisor-forwarded `pr_merged` once wt-f47's agent exited. |

**Worktrees left running:** none.

## Per-task summary

| Task | PR | Title | Codex rounds |
|---|---|---|---|
| T-259 | #186 | `fix(f48):` `_resolve_backend_url` uses grep+sed, not python3+yaml | 1 (demo path convention) + pass round 2 |
| T-257 | #188 | `fix(f48):` install mcp-server deps on any worktree with package.json | pass round 1 |
| T-256 | #189 | `chore(f48):` t244 demo binds mock server to port 0 | 2 (hardcoded abs path + deleted patch artifact, then overclaimed concurrency) |
| T-258 | #191 | `fix(f48):` worktrees auth contract unambiguous (Option B) | 2 (tasks_list docstring overclaimed scope; `list_worktrees` accepted any MCP bearer — security regression caught) |

## Commits brought in

### PR #186 — T-259 (merged 2026-04-22T17:39:19Z)

Replaced `python3 -c 'import yaml'` with grep+sed in `.cloglog/on-worktree-create.sh::_resolve_backend_url`; added unconditional stderr log so silent fallbacks are impossible; added `tests/test_on_worktree_create_backend_url.py` (4 cases).

### PR #188 — T-257 (merged 2026-04-23T04:32:28Z)

Dropped `WORKTREE_NAME == wt-mcp*` guard; now fires on any worktree containing `mcp-server/package.json`. Added `tests/test_on_worktree_create_mcp_install.py` (5 cases).

### PR #189 — T-256 (merged 2026-04-23T05:19:08Z)

Applied C2's `t244-demo-port-fix.patch`: mock server binds to port 0, shell polls `$WORK/mock-port`. Fixed hardcoded absolute paths in the demo capture so `showboat verify` reproduces on any checkout.

### PR #191 — T-258 / Option B (merged 2026-04-23T07:21:26Z)

- `src/agent/routes.py::list_worktrees` — full AUTH docstring, added `_: CurrentMcpOrDashboard` dep (codex-2 caught that the middleware presence-check alone left the bearer unvalidated — any garbage bearer under `X-MCP-Request: true` was accepted).
- `src/gateway/cli.py` — new `_require_dashboard_key(api_key, operation)` guard, called from `tasks_assign`, `tasks_list`, `agents_list`, and `_resolve_worktree`.
- `docs/ddd-context-map.md` — new `## Auth Contract` section (route prefix → credential shape + failure code tables).
- `docs/design.md § Authentication Flow` — per-route Auth Contract subsection.
- `tests/e2e/test_access_control.py` — 5 regression tests pinning: unauth 401, wrong dashboard 403, valid dashboard 200, agent token on non-agent route 403, invalid MCP bearer 401.

### Test count delta

Pre-wave: 654 tests. Post-wave: 738 (+84: +4 T-259, +5 T-257, 0 T-256, +5 T-258, +70 T-248 from the intervening PR #187). Coverage held at 91.30%. MCP server suite 83 passed throughout.

## Cross-agent coordination (highlight)

T-258's scope overlapped with PR #187 on `src/gateway/app.py` and `docs/ddd-context-map.md`. The agent followed its AGENT_PROMPT guard:

1. Detected open PR #187 via `gh pr list --state open`.
2. Emitted `mcp_tool_error` with `reason: "cross_agent_file_conflict"` to main inbox.
3. Received `resume_instruction` from supervisor ("do NOT split T-258, wait for #187 merge").
4. Waited on inbox.
5. Supervisor forwarded `pr_merged` for #187 once wt-f47's agent had exited (the webhook consumer only routes to the active PR-owner, so a later-starting agent on the same topic would miss the event otherwise).
6. Rebased cleanly — no textual conflicts in edited lines.
7. Resumed T-258 implementation.

This validates the full cross-agent-conflict pattern end-to-end and motivates T-262 (enrich `agent_unregistered` with PR URLs so the supervisor doesn't have to forward by hand).

## State after this wave

- **In main:**
  - `.cloglog/on-worktree-create.sh` no longer uses `python3 -c 'import yaml'` anywhere; all hooks now read `.cloglog/config.yaml` via grep+sed. Source-level regression guard pinned.
  - `mcp-server/npm install` fires on any worktree touching `mcp-server/package.json` (was previously `wt-mcp*` only).
  - Demo infrastructure at `docs/demos/wt-c2-mcp-rebuild/` uses port 0 for mock servers — removes a collision source.
  - `/api/v1/projects/{id}/worktrees` auth contract is now loud: docstring + per-route Depends + `docs/ddd-context-map.md § Auth Contract` section + `_require_dashboard_key` CLI guard. The silent-accept-any-MCP-bearer hole is closed (codex-2 catch).
- **Still un-promoted to prod:** backend code changes are minor (docstring + Depends + CLI guard) but SHOULD be picked up via `make promote` for full consistency.
- **New follow-up tasks filed during / immediately after this wave:**
  - T-262 (filed 2026-04-23) — enrich `agent_unregistered` event with PR URLs alongside `tasks_completed`; emit `pr_merged_notification` to main inbox. Motivated directly by the cross-agent-conflict coordination in this wave.

## Verification performed during the wave

- `make quality` green after every commit (6+ times across 4 PRs × multiple review rounds).
- E2E test `test_list_worktrees_rejects_invalid_mcp_bearer` pins the codex-2 security finding.
- End-to-end codex + opencode review pipeline validated on PR #191 itself post-fix deployment:
  - opencode turn 1 @07:02:34 — completed + consensus, 1 finding, 20.8s.
  - codex turn 1 @07:02:55 — completed + consensus, 2 findings, 217.3s.
  - Proves T-263/T-264 fixes (landed 06:26 UTC on main) are working end-to-end.

## Shutdown-artifact consolidation

`shutdown-artifacts/work-log.md` and `shutdown-artifacts/learnings.md` from the worktree are inlined into this file and `2026-04-23-f48-wave-f-learnings.md` respectively. The originals disappear when the worktree is removed in Step 7 below.
