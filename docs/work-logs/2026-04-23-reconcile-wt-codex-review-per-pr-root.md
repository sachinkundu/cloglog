# Work log — reconcile-wt-codex-review-per-pr-root

Reconcile-mode close-wave cleanup for a cleanly-completed worktree that was
left on disk after its agent unregistered. Invoked from `/cloglog reconcile`
Step 5.0 per the completed-cleanly predicate.

- **Worktree:** `wt-codex-review-per-pr-root`
- **Path:** `/home/sachin/code/cloglog/.claude/worktrees/wt-codex-review-per-pr-root`
- **Branch:** `wt-codex-review-per-pr-root`
- **Task:** T-278 — Per-PR codex review root (close the remaining
  host-level-fallback gap T-255 left open).
- **PR:** [#199](https://github.com/sachinkundu/cloglog/pull/199) — merged 2026-04-23 14:31 UTC.
- **Agent unregistered:** 2026-04-23T14:33:12Z (clean, `all_assigned_tasks_complete`).

## Commits

- `8873100` feat(review): resolve codex project_root per PR, not per host (T-278)

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|----------|-----|----------------|-------|
| wt-codex-review-per-pr-root | #199 | cooperative (agent already unregistered before reconcile) | Tier-1 `request_shutdown` skipped — list_worktrees had no row for this UUID; the `agent_unregistered` event was already in the main inbox at 14:33:12Z. Teardown proceeded with artifact consolidation and `git worktree remove --force`. |

## What shipped (from worktree work-log.md)

`resolve_review_source_root` returned ONE path per backend process before
T-278 — `settings.review_source_root or Path.cwd()`. On prod, that was the
pre-promotion `cloglog-prod` checkout, so every PR review read stale
`main`-side content for out-of-diff context. Codex's "file X currently does
Y" findings were systematically noisy. T-255 fixed the **host-level**
fallback (new `REVIEW_SOURCE_ROOT` env var + boot log). T-278 closed the
remaining **per-PR** gap.

### Changes

| File | Change |
|---|---|
| `src/gateway/review_engine.py` | New `async resolve_pr_review_root(event, *, project_id, worktree_query)` helper; new `_WorktreeQueryCtx` + `_worktree_query()` method on `ReviewEngineConsumer`. `_review_pr` now calls the helper per review. |
| `src/agent/interfaces.py` | New `IWorktreeQuery` Protocol + `WorktreeRow` DTO. `find_by_branch(project_id, branch_name) -> WorktreeRow \| None`. |
| `src/agent/services.py` | New `make_worktree_query(session) -> IWorktreeQuery` OHS factory. |
| `src/agent/repository.py` | New `find_worktree_by_branch_any_status`. `get_worktree_by_branch` keeps its `status='online'` filter for webhook routing; review resolver uses the no-status variant. |
| `docs/design/two-stage-pr-review.md` §9 | New authoritative section documenting the per-PR resolution rule, drift policy, DDD boundary. |
| `tests/gateway/test_review_engine.py` | +15 tests — resolver behavior, DDD boundary pin (leak-after-fix), integration. |
| `tests/agent/test_unit.py` | +6 tests — new repository method and factory. |
| `docs/demos/wt-codex-review-per-pr-root/` | Verify-safe demo: `demo-script.sh`, `proof.py` (three in-process proofs), `demo.md`. |

### Resolver semantics (spec §9.2)

1. **Primary** — `IWorktreeQuery.find_by_branch(project_id, event.head_branch)`;
   if the row exists AND `worktree_path` is on disk, return it. A
   `git -C <wt> rev-parse HEAD` probe logs `review_source_drift` when HEAD
   disagrees with the PR head SHA, but still prefers the worktree path —
   a slightly-stale worktree beats prod `main`.
2. **Fallback** — `settings.review_source_root or Path.cwd()` for PRs
   whose owning worktree is not on this host.

Never mutates the worktree — no `git fetch`, `checkout`, or `reset`.

### DDD boundary

Third Agent→Gateway / Review→Gateway OHS seam (the pattern established by
`IReviewTurnRegistry`). Gateway imports only `IWorktreeQuery` (under
`TYPE_CHECKING`) and `make_worktree_query` (inside the context manager);
never `src.agent.models` or `src.agent.repository`. Pin test
`TestReviewEngineDDDBoundary` asserts absence of the forbidden imports at
any indent.

## Code review

- **Codex turn 1/2** — `:pass:` with no findings. Amusing self-demonstration:
  codex was itself still reading from `/home/sachin/code/cloglog-prod/`
  paths during the review, which is exactly the bug this PR fixes. Future
  reviews on this host read the PR's actual worktree.

## Quality gate

Branch-local `make quality` was green: 783 passed, 1 xfailed, coverage
89.26%, demo verified byte-exact. GitHub CI: pass in 3m25s.
Reconcile-mode close-wave does not re-run `make quality` on main.

## State after this wave

- Local branch `wt-codex-review-per-pr-root` removed.
- Remote branch `origin/wt-codex-review-per-pr-root` removed via bot.
- Filesystem worktree `.claude/worktrees/wt-codex-review-per-pr-root` removed.
- Zellij tab `wt-codex-review-per-pr-root` closed.
- Close-off task `6a5a88ca` remains in backlog for the operator to complete.

## Learnings

Folded into `CLAUDE.md` in a separate reconcile commit:
1. `Path.cwd()` rule has two halves — host-level (T-255) AND per-PR (T-278).
   Any subprocess with a per-request source must use it, not the host fallback.
2. `get_worktree_by_branch` vs `find_worktree_by_branch_any_status` — keep
   their contracts distinct; webhook routing needs `status='online'` but
   review resolution only needs a filesystem path.
3. Third DDD OHS seam (`IWorktreeQuery` / `make_worktree_query`) follows the
   exact `IReviewTurnRegistry` / `make_review_turn_registry` shape. This is
   now the established pattern — copy verbatim for new seams.
