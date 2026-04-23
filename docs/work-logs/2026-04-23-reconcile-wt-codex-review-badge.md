# Work log — reconcile-wt-codex-review-badge

Reconcile-mode close-wave cleanup for a cleanly-completed worktree that was
left on disk after its agent unregistered. Invoked from `/cloglog reconcile`
Step 5.0 per the completed-cleanly predicate.

- **Worktree:** `wt-codex-review-badge`
- **Path:** `/home/sachin/code/cloglog/.claude/worktrees/wt-codex-review-badge`
- **Branch:** `wt-codex-review-badge`
- **Task:** T-260 — Visual indication on task card when codex picks up a PR for review.
- **PR:** [#198](https://github.com/sachinkundu/cloglog/pull/198) — merged 2026-04-23 14:01 UTC.
- **Agent unregistered:** 2026-04-23T17:03:17+03:00 (clean, `all_assigned_tasks_complete`).

## Commits

- `bcefb0d` feat(board): codex-reviewed badge on review-column task cards (T-260)
- `5eccb01` fix(board): project-scope codex projection + Rodney-captured visual demo (T-260 round 2)
- `1fab560` fix(demo): respect PG_HOST/PG_PORT env in demo psql seed (T-260 round 2)

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|----------------|-------|
| wt-codex-review-badge | #198 | cooperative (agent already unregistered before reconcile) | Tier-1 `request_shutdown` was skipped — list_worktrees had no row for this UUID; the `agent_unregistered` event was already present in the main inbox at 17:03:17. Teardown proceeded with artifact consolidation and `git worktree remove --force`. |

## What shipped (from worktree work-log.md)

A single boolean projection, `TaskCard.codex_review_picked_up`, sourced from
`pr_review_turns` via the Review context's Open Host Service factory.
Review-column cards render a "codex reviewed" pill next to the PR number /
merged badges the moment codex engages with the PR. The badge hides
automatically when a task moves back to `in_progress` because `TaskCard.tsx`
gates the pill on both `task.status === 'review'` AND
`task.codex_review_picked_up`.

### Backend
- New `IReviewTurnRegistry.codex_touched_pr_urls(*, project_id, pr_urls)` in
  `src/review/interfaces.py` + impl in `src/review/repository.py`.
- `src/board/routes.py::get_board` instantiates the registry via
  `make_review_turn_registry(session)` and joins the codex-touched set into
  each `TaskCard`. Board never imports `src.review.models` or
  `src.review.repository`.
- New SSE event `REVIEW_CODEX_TURN_STARTED = "review_codex_turn_started"`
  in `src/shared/events.py`; emitted on every `claim_turn` with
  `stage='codex'`.

### Contract & frontend
- OpenAPI contract updated; regenerated `frontend/src/api/generated-types.ts`.
- `PrLink.tsx` extended with a `codexReviewed` prop rendering a styled pill.
- `useSSE.ts` subscribes to the new event type.

### Tests (net new)
- `tests/board/test_codex_review_projection.py` — 6 real-DB integration tests.
- `tests/board/test_board_review_boundary.py` — 2 DDD pin tests.
- `tests/gateway/test_review_loop_sse_emission.py` — 3 invariant pins.
- `frontend/src/components/TaskCard.test.tsx` — 4 new cases.

## Code review rounds

- **Round 1 (codex turn 1/2):** 3 findings — 1 legitimate MEDIUM (project_id
  scoping), 2 false positives rooted in codex reading
  `settings.review_source_root` (prod checkout) rather than the branch tree.
- **Round 2 (codex turn 2/2):** 2 findings — 1 legitimate HIGH
  (PG_HOST/PG_PORT hardcoding), 1 false positive (same root cause as R1).

## Quality gate

`make quality` was green on the final commit (see worktree work-log.md for
the full matrix — 779 backend + 234 frontend tests, coverage 89.69%).
Reconcile-mode close-wave does not re-run `make quality` on main; main is
detached at `01d93ef` and origin/main at `2bad450` already carries this PR.

## State after this wave

- Local branch `wt-codex-review-badge` removed.
- Remote branch `origin/wt-codex-review-badge` removed via bot.
- Filesystem worktree `.claude/worktrees/wt-codex-review-badge` removed.
- Zellij tab `wt-codex-review-badge` closed.
- Close-off task `351ec2e9` remains in backlog for the operator to complete
  (reconcile cannot move the close-off task — the main agent owns it).

## Learnings

Folded into `CLAUDE.md` in a separate reconcile commit where they extend
existing guidance:
1. Frontend SSE — new `EventType` values must be added to `useSSE.ts`.
2. `showboat verify` treats every fenced code block as executable (including
   ```json``` blocks inside `showboat note` bodies).
3. `uv run python -c "..."` works under `showboat verify`; system `python3 -c`
   does NOT (no uv venv packages).
4. Demo seed with UNIQUE constraint — DELETE before INSERT so the row binds
   to the current demo project each run.
5. Rodney JS eval expects expressions, not statements — wrap multi-statement
   sequences in an IIFE.
6. Review engine reads from `settings.review_source_root` (the prod
   checkout on `main`), not the PR diff — codex false positives on files
   NOT in the diff are common.
7. Codex HIGH severity is not always self-consistent — verify reproducer
   claims with `uv run pytest <file>` before rewriting to satisfy them.
