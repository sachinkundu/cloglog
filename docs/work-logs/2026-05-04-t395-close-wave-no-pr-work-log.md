# Wave: t395-close-wave-no-pr — 2026-05-04

Single-worktree wave: `wt-t395-close-wave-no-pr` → PR #313 (merged 2026-05-04T05:35:38Z).

**First wave fold-committed under the new direct-to-main flow** (no `wt-close-*` branch, no PR — the very change PR #313 introduced is being closed via that change).

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|---------------|-------|
| wt-t395-close-wave-no-pr | #313 | cooperative (agent-driven, exit-on-unregister) | shutdown-artifacts inlined below |

## T-395 — Close-wave: skip PR, commit directly to main with bot identity

*from `work-log-T-395.md`*

### What shipped

Eliminated the close-wave PR round-trip (#311, #312 were the last two of the old shape). Close-wave now commits the wave-fold directly to `main` using `ALLOW_MAIN_COMMIT=1` and the GitHub App bot token, then calls `update_task_status(status="done")` for all close-off tasks in the wave — no branch, no PR, no user drag to done.

### Files touched

- `src/agent/services.py` — `update_task_status` carve-out: agent may mark a task `done` iff `task.close_off_worktree_id is not None` (with title-prefix + Operations-epic / Worktree-Close-off-feature placement check), AND the calling worktree owns the task AND its role is `main`. On `done`: recompute feature roll-up + clear `worktree.current_task_id`.
- `plugins/cloglog/skills/close-wave/SKILL.md` — Steps 10/13/13.5 rewritten for direct-to-main; push-rejection recovery (`reset --soft HEAD~1` → re-fetch → re-commit → push) included once.
- `plugins/cloglog/skills/reconcile/SKILL.md` — stale close-off recovery uses `update_task_status(status="done")` directly.
- `src/board/templates.py` — close-off template steps 4–8 describe direct-to-main.
- `src/board/services.py` — Worktree Close-off feature description updated.
- `CLAUDE.md` + both `install-dev-hooks.sh` copies — `ALLOW_MAIN_COMMIT=1` documented as approved for close-wave Step 13 + emergency rollback.
- `docs/invariants.md` — new entry for `ALLOW_MAIN_COMMIT` scope.
- Tests: 7 new in `tests/agent/test_unit.py` + `test_allow_main_commit_override_scope.py` (2) + rewritten `test_close_wave_skill_no_detached_push.py` (8). Total: 17 new pin tests pinning the carve-out, the ownership guard, the SKILL prose contract, and the override-scope invariant.

### Codex rounds (5)

1. Roll-up not recomputed + `current_task_id` not cleared on close-off `done`.
2. NULL-FK carve-out broken for legacy stale rows + stale demo exemption.
3. Push-retry recovery broken + title-prefix too broad + stale demo exemption.
4. Close-off template still described PR flow + CLAUDE.md / hooks wrong + stale demo exemption.
5. No ownership guard on close-off done carve-out.

All addressed before merge.

### Decisions

- **Option A** (relax user-only-done for close-off tasks) over Option B (require user drag). Close-off `done` is the post-push completion signal; no human review adds value.
- **Title prefix alone is insufficient.** Must verify Operations-epic + Worktree-Close-off-feature placement so a regular task titled "Close worktree X" cannot ride the carve-out.
- **Ownership = main role.** Only `role='main'` callers may close-off-done their own close-off tasks — prevents a sibling worktree agent from prematurely closing another worktree's card.

### Learnings (situational, left in this log; no generalised pin promotable to invariants.md beyond what already shipped)

- The demo classifier hashes the diff including everything except `docs/demos/`. **Demo exemption must be refreshed on every commit round**: finish all code commits → compute hash → update exemption → commit exemption *separately*. Updating the exemption mid-round produces a hash that doesn't match the final tip.
- The role guard works because registration derives `role` from path: paths containing `/.claude/worktrees/` get `role='worktree'`; everything else (including the main checkout) gets `role='main'`. Future role refactors must preserve that derivation or the close-off carve-out silently flips.

### Residual TODOs

- **Wave automation** (auto-trigger close-wave on the last merging PR) — out of scope for T-395; filed separately.
- If a future task adds another `ALLOW_MAIN_COMMIT=1` approved site, **both** `tests/plugins/test_allow_main_commit_override_scope.py` exemption list AND `docs/invariants.md` must be updated. Pin protects the test; the test protects the invariant.

## State after this wave

- Close-wave is now fold-commit-direct-to-main + close-off-done in one supervisor run; no PR for the wave-fold.
- Reconcile's stale close-off path uses the same direct-`done` shape.
- 17 new pin tests; quality gate green at coverage 88.61% on this run.
- Two prior-shape close-wave PRs (#311 #312) remain in history as the last of the old flow.
