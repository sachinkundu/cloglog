# Work Log: wt-t292-prod-branch-spec

**Date:** 2026-04-26
**Worktree:** wt-t292-prod-branch-spec
**Task:** T-292 — Spec: cloglog-prod tracks `prod` branch (not `main`)
**PR:** #219 (merged)
**Artifact:** `docs/design/prod-branch-tracking.md`

## Commits

- `9dc14fa` spec(T-292): cloglog-prod tracks prod branch, freeing main for dev worktree
- `697fe98` spec(T-292): address codex review — push origin/prod, ff-only pulls, T-prod-8 deps
- `91d8483` spec(T-292): address codex session 2/5 — soften memory claim, drop wrong risk, fix T-282 ID

## Files Changed

- `docs/design/prod-branch-tracking.md` (new, 268 lines after final revisions)

## Summary

Produced the design spec for moving the `cloglog-prod` worktree from tracking `main` to tracking a dedicated long-lived `prod` branch. Sections cover problem statement, proposal, branch model, promotion semantics, full audit of `main` references across Makefile / scripts / plugin skills + hooks / configs / CI / docs / memories, ordered migration plan with verification, interaction with the close-wave/reconcile detached-HEAD-push workaround, rollback story, risks/open questions, and nine follow-on impl tasks (T-prod-1 through T-prod-9) for the user to file.

## Review iterations

Two rounds of codex review, both substantive:

- **Session 1/5** — three findings, all valid: (a) `make promote` rewrite missed the `git push origin prod` step, so `origin/prod` would never advance; (b) T-prod-8 (pre-commit hook on `main`) was listed as independent of T-prod-7 but actually depends on it because close-wave/reconcile still commit to `main` until T-prod-7 retires that flow; (c) §5.4 said `git pull origin main` in close-wave/reconcile could STAY but plain `pull` is unsafe once dev has a writable local `main`. Fixed all three.
- **Session 2/5** — three more findings, all valid: (a) §1 over-claimed that `feedback_worktree_from_origin_main.md` exists "only" because of the lock — the unpushed-local-main hazard survives this spec until T-prod-7. Reworded; (b) §9 risk #4 claimed `git checkout main -- <path>` fails in the dev worktree due to the lock — empirically false (the lock only blocks HEAD-changing checkouts). Removed; (c) the "T-282" identifier in the original brief was stale — board T-282 is already complete (close-off task for T-281), and GitHub has no #282. Rewrote §7 with an "Identifier note" disambiguating the workflow from the stale ID; T-prod-7 now owns the rewrite directly.
- **Session 3/5** — pass with no findings.

## Notes for the impl wave

- The §10 task table is the proposed breakdown — T-prod-1 through T-prod-9. T-prod-1 gates everything; T-prod-7 must precede T-prod-8.
- Open question worth confirming with the user before impl starts (§9 risk #2): whether F-35 / Railway is dormant or imminent. If imminent, the prod-branch model interacts with whatever Railway expects.
- The original task brief says to "close T-282" — this would be wrong (T-282 is already complete and unrelated). T-prod-7 owns the close-wave/reconcile rewrite directly.
