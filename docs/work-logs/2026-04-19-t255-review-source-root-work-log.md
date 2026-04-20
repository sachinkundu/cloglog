# Work Log: T-255 — codex reviewer source-root fix

**Date:** 2026-04-19
**Worktree:** wt-reviewer-source-root
**Task:** T-255 — Codex reviewer reads cloglog-prod tree, not the PR's merge target — false negatives
**PR:** https://github.com/sachinkundu/cloglog/pull/159 (merged)

## Problem

F-36 review engine passed `Path.cwd()` to `codex -C`. Backend runs from `/home/sachin/code/cloglog-prod/`, which only advances on `make promote`. Any PR referencing code merged to `main` but not yet promoted got a false-negative review because codex saw the stale prod tree, not the PR's merge target. Observed on PR #158.

## Fix (Option B from the ticket)

Added `Settings.review_source_root: Path | None` (env `REVIEW_SOURCE_ROOT`). `_run_review_agent` now reads `settings.review_source_root or Path.cwd()`. Unset → dev fallback still works. Set → codex sees whatever tree the operator chose.

Also added `log_review_source_root(logger)` called at backend boot from `app.py`'s lifespan — logs `Review source root: <path> @ <sha> (<source>)`. A stale prod checkout is now visible in the log, not just in false-negative review comments.

## Commits

```
89abb0f fix(review): T-255 resolve review source root from settings, not cwd
```

## Files Changed

```
 .env.example                                                       |   8 +
 docs/demos/wt-reviewer-source-root/demo-script.sh                  | 110 ++++++++
 docs/demos/wt-reviewer-source-root/demo.md                         | 106 ++++++++
 docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md    |  14 +
 src/gateway/app.py                                                 |   7 +-
 src/gateway/review_engine.py                                       |  55 ++++-
 src/shared/config.py                                               |  15 +-
 tests/gateway/test_review_engine.py                                | 222 +++++++++++++++-
```

## Tests

- 7 new tests in `TestReviewSourceRoot` class in `tests/gateway/test_review_engine.py`:
  1. `test_resolve_returns_setting_when_set` — unit: resolve_review_source_root returns setting.
  2. `test_resolve_falls_back_to_cwd_when_none` — unit: returns Path.cwd() when setting is None.
  3. `test_project_root_from_setting` — integration: -C and cwd= both carry the setting's path.
  4. `test_project_root_falls_back_to_cwd_when_setting_none` — integration: fallback wired end-to-end.
  5. `test_dash_c_always_in_codex_argv` — regression guard against a refactor dropping -C.
  6. `test_log_review_source_root_bogus_path_no_exception` — boot probe tolerates missing dir.
  7. `test_log_review_source_root_real_git_dir` — boot probe captures a real 40-char SHA.
- Full review-engine test file: 71 tests passing.
- `make quality` green: lint, types, 569 tests (91% cov), contract, demo-verify.

## Demo

`docs/demos/wt-reviewer-source-root/demo.md` — six deterministic proofs (grep + python Settings load in two envs + pytest pass-count). Showboat verify re-runs on every `make quality`.

## Post-merge operator action

Prod deploy must export `REVIEW_SOURCE_ROOT=/home/sachin/code/cloglog`. First boot log must show `(settings.review_source_root)`, not `(Path.cwd() fallback)`, or the bug silently returns.
