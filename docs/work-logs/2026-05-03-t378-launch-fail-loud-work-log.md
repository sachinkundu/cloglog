# Wave: t378-launch-fail-loud — 2026-05-03

Single-worktree wave: `wt-t378-launch-fail-loud` → PR #310 (merged 2026-05-03T17:58:16Z).

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|---------------|-------|
| wt-t378-launch-fail-loud | #310 | cooperative (agent-driven, exit-on-unregister) | shutdown-artifacts inlined below |

## T-378 — Launch on-worktree-create.sh fail-loud + register-before-create pin

*from `work-log-T-378.md`*

### What shipped

Closed the 2026-04-24 silent-404 incident class on both worktree-bootstrap entrypoints by making the bootstrap script abort on any close-off-task failure, propagating that exit through the WorktreeCreate hook caller, and pinning step 4b/4c ordering in the launch SKILL.

- `.cloglog/on-worktree-create.sh`: missing `CLOGLOG_API_KEY` and any non-201 from `/api/v1/agents/close-off-task` now `exit 1` (was: warn-and-continue). Now sources `plugins/cloglog/hooks/lib/resolve-api-key.sh` and delegates `_resolve_api_key` to the canonical resolver, so the per-project layout (`~/.cloglog/credentials.d/<slug>`) works on multi-project hosts.
- `plugins/cloglog/hooks/worktree-create.sh`: removed `|| true` around the bootstrap call; captures status, logs FATAL, propagates the exit so the WorktreeCreate hook fails loud in lockstep.
- `plugins/cloglog/skills/launch/SKILL.md` Step 4b: explicit "Run this before Step 4c" callout naming the close-off-task dependency and the new pin test.

### Files touched

- `.cloglog/on-worktree-create.sh` — fail-loud + per-project resolver delegation
- `plugins/cloglog/hooks/worktree-create.sh` — propagate bootstrap exit
- `plugins/cloglog/skills/launch/SKILL.md` — Step 4b dependency callout
- `tests/plugins/test_launch_skill_register_before_on_worktree_create.py` (new, 3)
- `tests/plugins/test_on_worktree_create_fails_loud.py` (new, 4)
- `tests/plugins/test_worktree_create_hook_propagates_bootstrap_failure.py` (new, 2)
- `tests/test_on_worktree_create_per_project_credentials.py` (new, 3)
- `tests/test_on_worktree_create_backend_url.py` — fixture: PATH-shim curl + sentinel key
- `tests/test_on_worktree_create_mcp_install.py` — same fixture update

### Decisions

- Did not touch `|| true` on `uv sync --extra dev` (own warn guard immediately after; out-of-scope for the close-off-task surface).
- Sourced `resolve-api-key.sh` rather than re-inlining per-project lookup — matches agent-shutdown.sh / worktree-create.sh.
- Static + dynamic pin pair on the WorktreeCreate hook propagation.

### Review findings + resolutions

- **codex 1/5 [HIGH]**: `_resolve_api_key` only checked env + `~/.cloglog/credentials`, ignoring T-382 per-project layout. Fixed in 7b677e3 (sourced resolver lib + new per-project test file).
- **codex 2/5 [HIGH]**: `plugins/cloglog/hooks/worktree-create.sh` still wrapped the bootstrap call in `|| true` and exited 0 unconditionally. Fixed in 42f4572 (capture `$?`, FATAL log, propagate; static+dynamic pin file).
- **codex 3/5**: `:pass:`. Auto-merge gate held all six conditions; squash-merged via API at 2026-05-03T17:58:16Z (gh's local-branch cleanup tripped on main being checked out by another worktree, but the merge itself succeeded).

### Learnings

1. **Fail-loud at one entrypoint without auditing all callers leaves the guarantee leaky.** Codex caught a sibling `|| true` in the WorktreeCreate hook that would have masked the new exit codes. When converting warn-and-continue to exit-on-error, grep every caller for `|| true`, redirected stderr-only logging, and `set +e` islands.
2. **Bootstrap scripts that need credentials must use the shared resolver, not inline copies.** The per-project tier (T-382) shipped via `plugins/cloglog/hooks/lib/resolve-api-key.sh`; on-worktree-create.sh had diverged. Pattern: anywhere a hook resolves CLOGLOG_API_KEY, source the shared lib instead of re-implementing.

Both are situational guidance for future agents, not silent-failure invariants pinnable by a generalised test — left inline in this work log rather than promoted to `docs/invariants.md`. If a future audit can produce a generalised "no `|| true` around bootstrap-critical calls" pin, it earns an invariants entry then.

### Residual TODOs

- `|| true` on `uv sync --extra dev` (line 30 of `.cloglog/on-worktree-create.sh`) — still suppressed; deliberate out-of-scope. A future fail-loud sweep should convert it.
- `|| true` on the register POST in `plugins/cloglog/hooks/worktree-create.sh` line 65 — codex did not flag (different surface from close-off-task), but the same pattern applies.
- `gh pr merge --delete-branch` failure mode noted (gh's local cleanup vs API merge): documented in github-bot SKILL.md gotcha already; no action.

## State after this wave

- Worktree-create bootstrap path (both `.cloglog/on-worktree-create.sh` and `plugins/cloglog/hooks/worktree-create.sh`) is fail-loud on any close-off-task or credentials failure.
- Launch SKILL Step 4b explicitly precedes 4c with a dependency callout, pinned by `tests/plugins/test_launch_skill_register_before_on_worktree_create.py`.
- Per-project credentials path (`~/.cloglog/credentials.d/<slug>`) honoured by the bootstrap, pinned by `tests/test_on_worktree_create_per_project_credentials.py`.
- Quality gate: 1309 passed / 1 skipped / 1 xfailed at coverage 88.61%.
