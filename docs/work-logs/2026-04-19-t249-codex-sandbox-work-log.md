# Work Log — wt-codex-sandbox (T-249: codex reviewer bwrap bypass)

**Date:** 2026-04-19
**Worktree:** wt-codex-sandbox
**Task:** T-249 — Codex reviewer: use `--dangerously-bypass-approvals-and-sandbox` (true no-sandbox)
**Type:** standalone task (no spec/plan pipeline)
**PR:** https://github.com/sachinkundu/cloglog/pull/155 (merged)

## One-line summary

Swapped `--full-auto --sandbox danger-full-access` → `--dangerously-bypass-approvals-and-sandbox` in the codex reviewer invocation so bwrap is never launched, and pinned the argv shape with a regression test.

## Why it was needed

The earlier fix (cb466bb, 2026-04-18) assumed `--sandbox danger-full-access` skipped bwrap. It did not — it still invokes bwrap for `unshare-net`, which requires `CAP_NET_ADMIN`. On this host the kernel denies the capability and bwrap dies with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. Every PR review since fell back to a "sandbox error" message instead of actual findings — most visibly on PR #152.

## What changed

| File | Change |
|---|---|
| `src/gateway/review_engine.py` | Replace `--full-auto` + `--sandbox danger-full-access` with `--dangerously-bypass-approvals-and-sandbox`. Added a block comment warning future cleanups why bwrap must stay off. |
| `tests/gateway/test_review_engine.py` | New `test_codex_argv_uses_bypass_flag_not_sandbox` in `TestHandleOrchestration`. Four assertions: bypass flag present; `--sandbox`, `--full-auto`, `danger-full-access` each absent. Uses the existing `_create_subprocess` mock pattern. |
| `docs/demos/wt-codex-sandbox/` | New demo: PR #152 bwrap evidence, `codex exec --help` proof the flag exists, code diff, live codex round-trip asserting bwrap is absent, regression test + full module pass. |

## Quality gates

- `make quality` green: lint + mypy + 558 backend tests (1 xfail) + 90.84% coverage + contract check + demo verify.
- `tests/gateway/test_review_engine.py`: 64 passed (63 existing + 1 new).
- End-to-end verified by the merged PR itself — the codex reviewer bot posted a `:pass:` review on PR #155 listing ten files read outside the diff (AGENTS.md, ddd-context-map.md, app.py, config.py, github_token.py, review.md, review-schema.json, run-demo.sh, check-demo.sh), which directly proves bwrap is no longer blocking filesystem access.

## Timeline

1. Registered, started task, read `src/gateway/review_engine.py:539`.
2. Applied the 3-line argv swap + 4-line warning comment.
3. Wrote the regression-guard test (captured argv via `_create_subprocess` mock).
4. Installed dev extra (`respx`) that was missing from the worktree's venv — pre-existing gap, not from this task.
5. Fast-forwarded the worktree from origin/main (3 commits behind from T-247 / wt-fix-localhost) and discarded an unrelated `.mcp.json` edit that had already landed upstream.
6. Ran `make quality` — passed.
7. Produced demo via `cloglog:demo`, iterating on showboat `verify` determinism (grep for `[0-9]+ passed` instead of raw pytest output, filter codex output to stable markers).
8. Committed, pushed via bot, opened PR #155 with Demo / Tests / Changes / "Why the previous fix didn't work" sections.
9. Moved task to `review` with `update_task_status`.
10. Codex review returned `:pass:` — no inline findings, no change requests.
11. PR merged. `mark_pr_merged` called (idempotent alongside webhook).

## Follow-ups for main

None from this agent. T-249's review → done administrative move is the user's.
