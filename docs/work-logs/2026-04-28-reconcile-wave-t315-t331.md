# 2026-04-28 — reconcile-wave: t315 / t317 / t318 / t328 / t331

Five wt-* worktrees from the morning's parallel-launch wave landed cleanly on `main` but were not torn down — agents emitted `agent_unregistered`, backend rows were deleted, but local branches/worktree directories and zellij tabs remained. Reconcile picked them up and tore them down via the safe path (no buggy `close-tab` invocation; see T-339).

## Summary

| Worktree | Task | PR | Shutdown | Tab | Notes |
|---|---|---|---|---|---|
| wt-t315-move-plugin-docs | T-315 | [#249](https://github.com/sachinkundu/cloglog/pull/249) | cooperative | gone (closed earlier) | full work-log archived below |
| wt-t317-launch-host-doc | T-317 | [#248](https://github.com/sachinkundu/cloglog/pull/248) | cooperative | closed safely | aggregate log only |
| wt-t318-readme-init-prereqs | T-318 | [#250](https://github.com/sachinkundu/cloglog/pull/250) | cooperative | closed safely | full work-log archived below |
| wt-t328-protect-writes-failclosed | T-328 | [#251](https://github.com/sachinkundu/cloglog/pull/251) | cooperative | gone | full work-log archived below |
| wt-t331-close-wave-ff-only | T-331 | [#252](https://github.com/sachinkundu/cloglog/pull/252) | cooperative | gone | full work-log archived below |

All five completed cleanly per the predicate (`shutdown-artifacts/work-log.md` present, every assigned task `review` + `pr_merged=true`).

---

## T-315 — move plugin docs into plugin tree (PR #249)

Source: `wt-t315-move-plugin-docs/shutdown-artifacts/work-log.md`

Moved `docs/design/agent-lifecycle.md`, `docs/design/two-stage-pr-review.md`, and `docs/setup-credentials.md` into `plugins/cloglog/docs/` so the plugin ships these docs when installed on any project (making it self-contained). Updated all citations within plugin-owned files to use `${CLAUDE_PLUGIN_ROOT}/docs/<name>.md` rather than cloglog-specific paths. Added 7 pin tests.

### Codex review rounds (5/5 sessions consumed)

- **Session 1**: [CRITICAL] "Canonical location" banners contradicted existing tests; [HIGH] two-stage-pr-review had cloglog-internal cross-refs. Fixed both.
- **Session 2**: [MEDIUM] Plugin files used `plugins/cloglog/docs/` (hardcoded repo-relative) instead of `${CLAUDE_PLUGIN_ROOT}/docs/`. Fixed with bulk sed + new pin.
- **Session 3**: `:pass:`
- **CI failed**: T-318 had merged to main after branch creation, adding a bare `docs/setup-credentials.md` in init/SKILL.md that showed up in the merge commit CI used. Merged main + fixed the reference.
- **Session 4**: [HIGH] `test_no_bare_setup_credentials_path_in_plugin` had a false negative: filter applied to formatted violation string (which includes filename `/docs/setup-credentials.md`), silently passing violations inside the vendored doc itself. Fixed by filtering on raw line content.
- **Session 5**: `:pass:`

### Residual TODOs / context

- `plugins/cloglog/docs/two-stage-pr-review.md` still contains cloglog-repo-specific cross-references (`docs/ddd-context-map.md`, `docs/contracts/webhook-pipeline-spec.md`, `src/review/`, `src/gateway/`). A portability note was added at the top. Full portability is deferred follow-up work.
- The root docs (`docs/design/agent-lifecycle.md`, `docs/setup-credentials.md`, `docs/design/two-stage-pr-review.md`) now carry "Plugin mirror" banners and must be kept in sync with `plugins/cloglog/docs/` counterparts when edited. The banners are reminders; there is no automated sync check.
- Any future addition to `plugins/cloglog/skills/init/SKILL.md` (or any plugin file) that references `docs/setup-credentials.md` will be caught by `test_no_bare_setup_credentials_path_in_plugin`. The fix is to use `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md`.
- Ghost diff hazard: edits to plugin files MUST use the worktree-prefixed absolute path. Main repo's `plugins/cloglog/` is NOT the same as the worktree's copy. This PR hit ghost diffs once (caught and reverted before committing).
- Exemption hash must be refreshed after every commit round — this PR refreshed it 5 times. Pattern: `git diff "$MERGE_BASE" HEAD -- . ':(exclude)docs/demos/' | sha256sum`.

---

## T-317 — document launch.sh host-specificity (PR #248)

Source: `wt-t317-launch-host-doc/shutdown-artifacts/work-log.md` (aggregate only)

Added operator-host-specificity warning to launch SKILL.md Step 4e and a pin test. No code changes — documentation and test only. Closes F-53 Phase 1.4.

---

## T-318 — README + init prerequisites (PR #250)

Source: `wt-t318-readme-init-prereqs/shutdown-artifacts/work-log.md`

Created `README.md` at the project root and added a `## Prerequisites` section to `plugins/cloglog/skills/init/SKILL.md`, both documenting the operator install flow for the cloglog plugin. Added 10 pin tests in `tests/plugins/test_readme_and_init_prereqs.py` to prevent regression.

This resolves Phase 2 Step 5 of `docs/design/plugin-portability-audit.md`.

### Files changed

- `README.md` (new) — top-level project documentation: what cloglog is, 4 prerequisites for `/cloglog init`, two-phase quick start, session/agent-launch commands, links to further docs
- `plugins/cloglog/skills/init/SKILL.md` — `## Prerequisites` section added before Step 1
- `tests/plugins/test_readme_and_init_prereqs.py` (new) — 10 pin tests
- `docs/demos/wt-t318-readme-init-prereqs/exemption.md` — classifier exemption (docs-only diff)

### Codex review findings addressed

- `make dev` corrected to port 8000 only; `make prod` → port 8001 (was wrong in README)
- Plugin portability claim qualified: "long-term goal", links to audit doc
- Init prereq 4 re-run note narrowed: prereq 3 (DASHBOARD_SECRET) is satisfied after bootstrap, but prereq 4 (GitHub App: PEM + env vars) is host-local and must be set independently

### Residual TODOs / context

- T-318 covers only documentation. The actual portability fixes (Phase 0: `import yaml` removal, Phase 1: script vendoring, Phase 2 steps 6-9) are separate F-53 tasks and remain unimplemented.
- The README intentionally avoids claiming the plugin works with other projects today — the portability audit lists concrete blockers (unresolved placeholders in init Step 3, `import yaml` in hooks, etc.).
- The `## Prerequisites` section in init SKILL.md was added before Step 1. If the init skill gains a new prerequisite (e.g., after the `claude plugins install` marketplace flow is finalized), update both README.md and the Prerequisites section in lockstep so the pin tests continue to pass.
- Pin tests assert substring presence; if wording changes significantly, update the tests too (they're in `tests/plugins/test_readme_and_init_prereqs.py`).

---

## T-328 — protect-worktree-writes fail-closed on missing config (PR #251)

Source: `wt-t328-protect-writes-failclosed/shutdown-artifacts/work-log.md`

Fixed a fail-open bug in `plugins/cloglog/hooks/protect-worktree-writes.sh`: when `.cloglog/config.yaml` is absent, the hook previously exited 0 (allow all writes). Changed to exit 2 with a clear operator message. Added two pin tests to lock in the boundary between fail-closed (config missing) and intentional no-op (config exists, no `worktree_scopes` key).

### Files changed

- `plugins/cloglog/hooks/protect-worktree-writes.sh` — `find_config ... || exit 0` → `find_config ... || { echo "Blocked: ..."; exit 2; }`
- `tests/plugins/test_parse_worktree_scopes.py` — added `test_hook_fails_closed_when_config_missing` and `test_hook_allows_when_no_scopes_key`

### Test results

20 tests in `test_parse_worktree_scopes.py`, all passing. Full `make quality` passed (1019 passed, 0 failed).

### Residual TODOs / context

- The T-313 work (Phase 0b of F-53) already handled replacing `import yaml` with the stdlib parser (`parse-worktree-scopes.py`). T-328 closed the last fail-open hole in that same hook. The hook is now fully fail-closed on all error paths: missing config → exit 2, malformed config → exit 2, parser error → exit 2.
- The other four scalar-key parser sites (`worktree-create.sh`, `quality-gate.sh`, `enforce-task-transitions.sh`, launch skill template) were handled in Phase 0a. All are now using the shared `parse-yaml-scalar.sh` helper.
- The `test_hook_allows_when_no_scopes_key` test documents an intentional design decision: projects without `worktree_scopes` get a no-op hook (all writes allowed). This is documented in the test docstring. Future tasks that change this behavior must update that test.

---

## T-331 — close-wave skill: ff-only main before branching (PR #252)

Source: `wt-t331-close-wave-ff-only/shutdown-artifacts/work-log.md`

Added `git fetch origin` + `git merge --ff-only origin/main` immediately before `git checkout -b wt-close-...` in Step 10 of `plugins/cloglog/skills/close-wave/SKILL.md`.

The race: Step 9 fetches and fast-forwards main, but Step 9.5 (`make sync-mcp-dist`) runs between Step 9 and Step 10. Any PR merged during Step 9.5 advances `origin/main` but not local `main`, so the close-wave branch is created from a stale base. Codex then sees a branch that pre-dates the implementation commit and flags work-log claims as false.

Observed on PR #242 (T-327 close-wave for T-314): manual rebase onto `origin/main` fixed it at the time. This fix closes the window permanently.

### Files touched

- `plugins/cloglog/skills/close-wave/SKILL.md` — Step 10 updated with re-fetch block
- `tests/plugins/test_close_wave_skill_no_detached_push.py` — new pin test

### Decisions

- Added the re-fetch block directly to Step 10's bash snippet (not a prose note) so operators copy-paste the complete correct sequence.
- Prose explains the Step 9.5 window explicitly so future readers understand WHY the re-fetch is needed even though Step 9 already fetches.
- Pin test slices to Step 10 section only (between `## Step 10:` and `## Step 10.5:` markers) so it doesn't pass on the Step 9 or Step 13 ff-only occurrences.

### Residual TODOs / context

None. Self-contained skill fix. The Step 10 change is the only place the race window existed; Step 9's ff-only is still load-bearing for the normal path (no merge between Steps 8 and 9.5).

---

## Reconcile-cycle learnings

- **Backend rows can outlive nothing.** All five `agent_unregistered` events fired and the backend cleared the worktree rows immediately, but local branches, worktree directories, and zellij tabs remained — there is no auto-cleanup binding those three to the row deletion. Close-wave/reconcile is the only thing that ties them together.
- **The buggy `close-tab` path matters.** Reconcile would normally invoke close-wave per-worktree (Step 5.0 delegation), and close-wave's Step 5c uses bare `zellij action close-tab` which closes the focused tab (the supervisor's own). Worked around for this wave by closing tabs via `go-to-tab-name <wt> && close-tab && go-to-tab-name <supervisor>`. Permanent fix tracked in T-339 (expedite, F-50).
- **Five PRs in one wave is fine when they're independent.** The agents launched in parallel landed PRs #248–#252 within a 30-minute window with no merge conflicts; the `gh pr merge` order didn't matter. The retracted "no parallel worktrees per feature" directive was the right thing to retire — feedback memory `feedback_parallel_when_unrelated.md` covers this.
