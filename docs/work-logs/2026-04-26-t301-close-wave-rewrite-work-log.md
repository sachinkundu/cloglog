# Work Log — wt-t301-close-wave-rewrite

## Task

**T-301** — Retire close-wave/reconcile detached-HEAD push + main-commit pre-commit guard (T-prod-7 + T-prod-8).
Feature: F-50 (Worktree Close-off).

## PR

- **#230** — `chore(close-wave): retire detached-HEAD push; guard direct main commits` — merged.

## What shipped

### T-prod-7 — Branch + PR flow for close-wave / reconcile fold commits

- `plugins/cloglog/skills/close-wave/SKILL.md`
  - Step 10 introduces `git checkout -b wt-close-<date>-<wave-name>`; previous Step 10 (Run Quality Gate) renumbered to 10.5.
  - Step 13 rewritten — bot-authenticated push + `gh pr create` against `main`, post-merge ff sync, `git branch -D` cleanup. Explicit "never commit directly to main" guidance.
  - Header description and "Callable from reconcile" note updated: "quality gate on main" → "quality gate on the close-wave branch".
- `plugins/cloglog/skills/reconcile/SKILL.md`
  - Step 5 auto-fix block prepended with "Reconcile fixes never commit on `main`" recipe — `wt-reconcile-<date>-<topic>` branch + bot-authenticated PR + ff sync. Calls out the dev-clone pre-commit guard's `ALLOW_MAIN_COMMIT=1` override as emergency-rollback-only.

### T-prod-8 — Pre-commit guard against direct `main` commits

- `scripts/install-dev-hooks.sh` (new, executable). Resolves `.git/hooks/` via `git rev-parse --git-path hooks` so it works from worktrees too. Idempotent (overwrites the managed hook in place). Writes a `pre-commit` hook that rejects commits on `main` unless `ALLOW_MAIN_COMMIT=1`.
- `CLAUDE.md` Runtime & Deployment — one-line install instruction with cross-references to the close-wave / reconcile branch + PR flow.

### Pin tests

- `tests/plugins/test_close_wave_skill_no_detached_push.py` — 5 assertions: absence of retired patterns (`git checkout --detach origin/main`, `git push origin HEAD:refs/heads/wt-close-`, `chore-close-`), presence of new branch + PR flow, presence of bot-authenticated `GH_TOKEN="$BOT_TOKEN" gh pr create`.
- `tests/plugins/test_reconcile_skill_no_detached_push.py` — 5 assertions: same shape for reconcile.
- `tests/test_install_dev_hooks_guard.py` — 5 behavioural tests: installer creates an executable hook, guard blocks commit on main, override allows commit, wt-* branch commits pass through, idempotent re-run.

## Quality gate

- Baseline (pre-change): 898 tests passed, 88.4% coverage.
- After: 911 tests passed (+13), 88.4% coverage. `make quality` green end-to-end (lint + types + tests + contract + demo-check + MCP server build/tests).

## Test Report

- **Delta:** +13 tests across 3 new files.
- **Strategy:** mix of *absence* asserts (load-bearing for retired patterns per the leak-after-fix rule — bug looked correct in tests because the workaround "worked"), *presence* asserts (catch silent deletion of the new flow without re-introducing the old one), and *behavioural* tests for the install script (only level that proves the hook fires, since unit tests would just re-quote the heredoc).
- **Thinking:** the install script is operator-run, per-clone, never imported by other code. End-to-end exercise in a temp `git init -b main` repo proves: (a) the hook is installed and executable, (b) it blocks correctly, (c) it surfaces `ALLOW_MAIN_COMMIT` in stderr so operators can find the override, (d) it allows the override, (e) it does not fire on `wt-*` branches, (f) re-running the installer is safe.

## Demo

Auto-exempt (static allowlist). Every changed file is developer infrastructure (`CLAUDE.md`, `plugins/cloglog/skills/`, `scripts/`, `tests/`).

## Code review

- **Codex round 1:** 2 MEDIUM findings on bare `gh pr create` snippets in both SKILL.md files — the new branch+PR flow showed unauthenticated `gh pr create` examples instead of the canonical bot-authenticated form from `plugins/cloglog/skills/github-bot/SKILL.md:34,58-63`. An operator following the snippets literally would open the PR under their personal `gh auth` and break the bot-identity invariant.
- **Round 1 fix (commit `147371e`):** restored the bot-authenticated `BOT_TOKEN=$(...)` / `git remote set-url ...` / `git push -u origin HEAD` / `GH_TOKEN="$BOT_TOKEN" gh pr create ...` sequence in both SKILLs, and grew both pin tests with a positive `'GH_TOKEN="$BOT_TOKEN" gh pr create'` substring assertion so a future bare-`gh` revert fails loudly.
- **Codex round 2:** `:pass:` — no verified correctness issues.
- Auto-merge gate fired after CI passed; PR squash-merged.

## State after this work

- Close-wave / reconcile fold commits flow through `wt-close-*` / `wt-reconcile-*` PRs — same shape every other agent uses.
- Detached-HEAD push workaround is retired (and pinned out by absence asserts).
- Operator install: `bash scripts/install-dev-hooks.sh` once on the dev clone (documented in CLAUDE.md). Override `ALLOW_MAIN_COMMIT=1` reserved for emergency-rollback cherry-picks.
- T-282 (board task `c86883e3-5bb5-4c3a-bd62-c05b483f834c`) — per `docs/design/prod-branch-tracking.md` §7 identifier note, that ID was already used as a close-off task for T-281 and is unrelated to this workflow. Nothing on the board needs to be closed for this PR.

## Learnings & Issues

See `learnings.md`.
