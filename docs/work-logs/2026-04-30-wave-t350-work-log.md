# Wave t350 — work log

**Date:** 2026-04-30
**Wave:** wave-t350
**Worktrees in scope:** `wt-t350-review-engine-repo-routing`

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|---------------|-------|
| `wt-t350-review-engine-repo-routing` | [#273](https://github.com/sachinkundu/cloglog/pull/273) | cooperative + manual tab close | Launcher PIDs 863412/863416 lingered (third reproduction of T-352). |

## What shipped (T-350)

Repo-aware PR review root resolution. Closes the failure that produced antisocial PR #2's hostile fabricated review citing cloglog's `README.md`/`CLAUDE.md`/`docs/ddd-context-map.md`.

Mechanism: new `settings.review_repo_roots` — a JSON env-var map from `owner/repo` → filesystem path. The resolver now has four strategies in order:

1. **Path 0** — `pr_url` binding (T-281, unchanged).
2. **Path 1** — branch lookup (T-278, unchanged).
3. **Path 2 (NEW)** — per-repo registry; require git directory at the configured path.
4. **Path 3** — legacy host-level fallback (`settings.review_source_root`, T-255).

When the registry is non-empty AND the PR's `repo_full_name` is absent from it AND no worktree owns the branch → `resolve_pr_review_root` returns `None` and the engine posts a one-shot `UNCONFIGURED_REPO` skip comment. Posting nothing is strictly better than posting wrong.

### Files touched

- `src/gateway/review_engine.py` — Path 2 + refusal branch + `_resolve_main_clone_anchor` + `_git_common_dir` helpers; degraded single-turn path now respects the registry refusal subset
- `src/gateway/review_skip_comments.py` — new `SkipReason.UNCONFIGURED_REPO`
- `src/shared/config.py` — `Settings.review_repo_roots` (`dict[str, Path]` JSON env var) + tightened `review_source_root` docstring
- `tests/gateway/test_review_engine.py` — `TestResolvePrReviewRootRepoRouting` class: 10 tests covering both acceptance branches (skip unrelated repo, cloglog close-wave routes, branch lookup unchanged for cloglog + foreign, registry lookup, temp-checkout anchor for registry + Path 1 common-dir, stale-registry fall-through, Path 2 non-git refusal, degraded-path refusal)
- `.env.example` — documents `REVIEW_REPO_ROOTS` JSON shape and the multi-repo deployment requirement
- `docs/invariants.md` — updated resolver invariant to four strategies + `PrReviewRoot | None` refusal contract
- `docs/design/two-stage-pr-review.md` — §9.2 renumbered + Path 2 inserted
- `docs/demos/wt-t350-review-engine-repo-routing/` — Showboat demo with synthetic webhook events driving both acceptance branches

### Decisions

- **Option (a) registry over option (b) hard-fail-only.** Registry is the long-term answer because hand-created / external-fork / close-wave PRs for any configured repo need a way to route correctly. Hard-fail alone would refuse the cloglog close-wave case too.
- **Backward compat: empty registry preserves legacy behaviour.** Existing T-278/T-281 resolver tests pass unchanged. **The bug is only fixed in production once the operator sets `REVIEW_REPO_ROOTS`** — see operator follow-up below.
- **`_git_common_dir` derivation > requiring per-repo registry entries everywhere.** Foreign-repo Path 1 hit (registered worktree, no registry entry) can still derive the right main clone from the worktree's own metadata.

### Codex review (5 rounds, all caught real bugs)

| Round | Severity | Finding |
| --- | --- | --- |
| 1 | MEDIUM + CRITICAL | `.env.example` / `docs/invariants.md` / two-stage-pr-review left without `REVIEW_REPO_ROOTS` requirement → safety fix would stay disabled on fresh deploys; demo's first grep counted *every* `async def test_` (79) instead of the T-350 class (5) |
| 2 | MEDIUM | SHA-mismatch temp-checkout still anchored at `settings.review_source_root` regardless of which path won — registry-routed antisocial PR would `git worktree add` against cloglog-prod's object DB |
| 3 | MEDIUM | Foreign-repo Path 1 hits (registered worktree, no registry entry) anchored at `review_source_root`; fixed via `_git_common_dir` derivation |
| 4 | MEDIUM | Registry entries used unconditionally; stale path silently overrode valid Path 1 hit. Validate via `_git_common_dir` before using |
| 5 | HIGH + MEDIUM | Path 2 accepted any `is_dir()` (not just git); degraded single-turn path in `_run_review_agent` hard-coded `review_source_root` and bypassed refusal entirely |

## Operator follow-ups (REQUIRED)

The fix is live but inert until the operator sets `REVIEW_REPO_ROOTS`. On the production host:

```
REVIEW_REPO_ROOTS='{"sachinkundu/cloglog":"/home/sachin/code/cloglog-prod","sachinkundu/antisocial":"/home/sachin/code/antisocial"}'
```

Add to the backend env (systemd / `.env` per host convention) and restart the service. Until that's done, the legacy host-level fallback still routes every webhook to cloglog-prod.

Also: delete or strikethrough the bogus review on antisocial PR #2 with an apology comment from the operator account (codex's session-1/5 review).

## Learnings & Issues

Candidates for CLAUDE.md (operator decision):

- **Resolver-fix safety nets must be opt-in by config, not by code.** Backward compat tests pass even when the bug is unfixed — the fix only activates once `REVIEW_REPO_ROOTS` is set. Document this loudly in `.env.example` and the PR body, otherwise the deploy lands and the fabricated reviews continue.
- **`git worktree add --detach` on a foreign SHA succeeds *only* when the SHA already lives in the host repo's object DB.** That's how antisocial's commit ended up checked out under cloglog-prod's review-checkouts dir — the engine had previously fetched it. New invariant: temp-checkout anchor must be derived per-PR from the resolved review root, not pinned to a single host root.
- **Linked-worktree `git rev-parse --git-common-dir`'s parent always points at the main clone.** Use this instead of trying to track main-clone paths in config — works even when only the worktree row is registered.
- **`is_dir()` is not enough to validate a registry path** — must require a git directory, otherwise a typo silently degrades the resolver.

### Wave-level integration issue

- **Launcher PIDs lingered after `unregister_agent`** (PIDs 863412/863416). Third reproduction of T-352. Reproducible enough to be a clean fix candidate; bumping the priority.

## State after this wave

- T-350 implementation merged: review engine no longer fabricates cross-repo reviews once `REVIEW_REPO_ROOTS` is set.
- All three expedite-priority work items from yesterday closed (T-346, T-348, T-350).
- T-352 reproduces consistently — should be picked up next.
- No worktree agents currently running.
