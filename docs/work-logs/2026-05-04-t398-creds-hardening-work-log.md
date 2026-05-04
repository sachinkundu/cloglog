# Wave: t398-creds-hardening

Single-task wave folding T-398 (Per-project credentials hardening — three guards).

## Worktree

| Worktree | Branch | PR | Shutdown path |
|----------|--------|----|---------------|
| wt-t398-creds-hardening | wt-t398-creds-hardening | [#314](https://github.com/sachinkundu/cloglog/pull/314) | cooperative (agent_unregistered emitted; close-wave fell through to tab-close because exit-on-unregister.sh did not fire — see T-390 recurrence) |

PR #314 — `feat(credentials): T-398 per-project credentials hardening — three guards` — merged 2026-05-04 06:52 UTC by user past the 5/5 codex session limit.

## Per-task work log

### T-398 — Per-project credentials hardening (`from work-log-T-398.md`)

#### What was done

Implemented all three T-398 credential hardening guards in a single PR across 5 codex review rounds.

**Guard 1 — `/init` always writes to `credentials.d/<slug>`:**
- `plugins/cloglog/skills/init/SKILL.md`: Phase 1 detection now treats `env` or `per-project` credentials as bootstrapped only when `project_id` is set in `config.yaml`. Legacy global `~/.cloglog/credentials` is treated as missing on bootstrapped repos, routing through the repair/mint path.

**Guard 2 — `register_agent` verifies `project_id` before backend POST:**
- `mcp-server/src/server.ts`: Inline `/api/v1/gateway/me` preflight before `handlers.register_agent()`. On `config.yaml` vs API key `project_id` mismatch, returns `isError: true` with an operator-facing diagnostic naming the expected credential path. Backend side effects (worktree upsert, agent token rotation, `WORKTREE_ONLINE` emission) never fire on mismatch.
- `ensureProject()` hardened: checks `config.yaml` `project_id` against `/gateway/me` before caching `currentProjectId`, preventing `update_project` (called by `/cloglog init` before `register_agent`) from operating on the wrong project.
- `createServer()` accepts `opts?: { configRoot?: string | null }` — `null` skips the check (for tests), `undefined` auto-detects from `process.cwd()`.

**Guard 3 — strict fallback when `project_id` is set:**
- `mcp-server/src/credentials.ts`: Refuses legacy `~/.cloglog/credentials` fallback when `project_id` is set, for both slug-present (per-project file missing) and slug-null (non-slug-safe path) cases. `ProjectIdSetMissingCredentialsError.projectSlug` widened to `string | null`.
- `plugins/cloglog/hooks/lib/resolve-api-key.sh`: Same logic in bash — slugless check after the slug block.
- `plugins/cloglog/skills/launch/SKILL.md` `_api_key()`: already correct (Guard 3 outside slug block).

**Docs and runbooks:** `docs/setup-credentials.md`, `plugins/cloglog/docs/setup-credentials.md`, `plugins/cloglog/skills/launch/SKILL.md` (relaunch timeout checklist + diagnostic step 4), `plugins/cloglog/skills/setup/SKILL.md` (continuation-phase diagnostic and `mcp_unavailable` bullet).

**Tests added:** `mcp-server/tests/credentials.test.ts` (Guard 3 slugless + lazy-resolve `{ configRoot: null }`), `mcp-server/tests/server.test.ts` (Guard 2 mismatch verifies no backend POST and no cached `project_id`), `tests/plugins/test_init_bootstrap_skill.py`, `tests/plugins/test_launch_skill_per_project_credentials.py`, `tests/plugins/test_init_mints_per_project_credentials.py`, `tests/test_mcp_register_agent_verifies_project_id.py`.

#### Codex review history

5 sessions — all findings addressed; bot exhausted session limit; merged on human review.

- Round 1: Guard 2 was post-registration → moved preflight before POST.
- Round 2: launch SKILL `_api_key()` Guard 3, `docs/setup-credentials.md` updated.
- Round 3: `ensureProject()` was caching on mismatch path → inline local variable.
- Round 4: `ensureProject()` still unchecked for pre-registration tools → `createServer(opts)` + config check.
- Round 5: Guard 3 slugless bypass in `credentials.ts` and `resolve-api-key.sh`, `setup/SKILL.md` line 115, `setup-credentials.md` item 3 contradiction.

#### Residual TODOs / context the next task should know

- The three guards are now consistent across TS (`credentials.ts`), bash (`resolve-api-key.sh`, `launch.sh _api_key()`), and the MCP server registration flow.
- `ProjectIdSetMissingCredentialsError` accepts `string | null` for `projectSlug`; existing call sites with non-null slugs still work unchanged.
- `createServer(client, opts)` is backward-compatible — production `index.ts` passes no opts and auto-detects `configRoot` from `process.cwd()`.
- T-398 acceptance criteria fully satisfied.

## Learnings & Issues

### Recurrence: exit-on-unregister.sh did not fire (T-390)

After T-398's agent emitted `agent_unregistered` at 09:53:41, claude PID 3591654 (parent: launcher PID 3591634) was still alive at 09:55+, with the inbox-monitor `tail` still attached. `/tmp/agent-shutdown-debug.log` showed no `exit-on-unregister.sh scheduled TERM` line for PID 3591654 — same regression as T-376. Close-wave Step 6 surfaced the surviving process; close-wave fell through to closing the zellij tab to terminate. T-390 already tracks investigation; recurrence noted on the task.

### Quality gate

`make quality` on `main` after the merge passed: 1348 tests passed, 1 skipped (per-task work-log schema — no `work-log-T-*.md` in tree), 1 xfailed (known cross-feature `pr_url` reuse guard, T-155). No integration issues to fix.

### Routing (Step 11)

- T-390 recurrence noted on T-390 itself (workflow gotcha is task-tracked, not docs-tracked).
- No new silent-failure invariants (the three guards are themselves test-pinned).
- No new SKILL/agent-prompt updates beyond what the PR shipped.

## State After This Wave

- Per-project credential discipline now enforced on three independent code paths: TypeScript credential loader, bash credential helpers, and the MCP server's `register_agent` / `ensureProject` preflights.
- Bootstrapped repos (those with `project_id` in `config.yaml`) refuse to fall back to the legacy global `~/.cloglog/credentials` file, eliminating the silent-401 cross-project credential leak.
- Four parallel worktrees launched in this session and remain in flight: T-370 (wt-t370-inbox-monitor-hook), T-407 (wt-t407-review-db-errors), T-408 (wt-t408-structured-logs), T-409 (wt-t409-codex-status-badge).
