# Wave: t409-codex-status-badge

Single-task wave folding T-409 (Replace "codex reviewed" boolean badge with state-aware codex status).

## Worktree

| Worktree | Branch | PR | Shutdown path |
|----------|--------|----|---------------|
| wt-t409-codex-status-badge | wt-t409-codex-status-badge | [#318](https://github.com/sachinkundu/cloglog/pull/318) | cooperative + tab-close (T-390 recurrence pattern) |

## Per-task work log

### T-409 — 7-state CodexStatus discriminated badge (`from work-log-T-409.md`)

#### What was built

Replaced the binary `codex_review_picked_up` Kanban badge with a 7-state discriminated `CodexStatus`: `not_started / working / progress / pass / exhausted / failed / stale`. Motivating failure: PR #314 stayed `true` through the round-5 stall after the backend HUP because the boolean cannot represent in-flight vs stuck vs done.

**Review context (`src/review/`):** `interfaces.py` adds `CodexStatus` (StrEnum), `CodexProgress` (frozen dataclass), `CodexStatusResult`, and extends `IReviewTurnRegistry` with `codex_status_by_pr(*, project_id, pr_url_to_head_sha, max_turns)`. `repository.py` adds the batch query and `_derive_codex_status`. Key semantics: FAILED uses `max(current, key=turn_number)` not `any(failed)` so retry turns supersede earlier failures; `db_error` outcome (T-407) excludes from PASS and triggers FAILED.

**Board context (`src/board/`):** `models.py` adds `pr_head_sha VARCHAR(64)` nullable column on `Task`. `repository.py` adds `shared_pr_urls_in_project` (project-wide, unfiltered — finds duplicates regardless of `exclude_done`) and `find_projects_by_repo` (returns ALL matching projects, not `.limit(1)`). `routes.py` does dual-path projection — tasks with unique `pr_head_sha` get discriminated `CodexStatus`; tasks without sha or with shared `pr_url` fall back to legacy boolean. `update_task` clears `pr_head_sha=None` when `pr_url` changes. `schemas.py` `TaskCard` gains `codex_status: CodexStatus | None` and `codex_progress: CodexProgress | None`; `codex_review_picked_up` retained as deprecated.

**Migration:** `b2c3d4e5f6a1_add_pr_head_sha_to_tasks.py` linear chain off `479ae109c254` (T-407's `add_outcome_to_pr_review_turns`).

**Gateway (`src/gateway/webhook_consumers.py`):** handles `PR_OPENED` and `PR_SYNCHRONIZE` to write `pr_head_sha` on the matching task. `_update_pr_head_sha` iterates ALL matching projects via `find_projects_by_repo` so cross-project PR tracking is correct.

**Frontend (`frontend/src/`):** `PrLink.tsx` `CodexBadge` renders each state with distinct colors (blue/animated for working, blue/static for progress, green for pass, red for failed/exhausted, amber for stale). `TaskCard.tsx` gates `codexStatus` on `task.status === 'review'`. `generated-types.ts` regenerated from updated baseline OpenAPI.

**Tests:** `tests/board/test_codex_status_projection.py` — 18 projection tests covering all states including retry semantics, db_error override, stale, cross-project isolation. `tests/gateway/test_webhook_consumers.py::TestPrHeadShaWebhookUpdate` — multi-project SHA update regression.

#### Codex review sessions

5 sessions (cap). Session 4 returned `:pass:` but merge state was `DIRTY` (conflict in `schemas.py` from T-407's parallel merge). After resolving, session 5 found 3 issues (CRITICAL: dual Alembic heads; 2× HIGH: db_error not projected, single-project SHA update). All fixed in the final push. Merged by human reviewer at the cap.

#### Residual TODOs / context the next task should know

- **`codex_queued` state deferred** — needs a separate "enqueue" webhook event shape that doesn't exist yet. The 7 shipped states cover all observable states from `pr_review_turns` rows.
- **`xfailed test_pr_url_reuse_blocked_cross_feature`** — project-wide PR URL uniqueness enforcement is a separate work item (T-155). The `shared_pr_urls_in_project` safeguard routes duplicate-pr_url tasks to the legacy boolean path rather than blocking at write time.
- **`codex_review_picked_up` still on the wire** (deprecated comment added). Future cleanup task should remove it after confirming no external consumers rely on it.
- **`find_projects_by_repo` trailing-substring match** — if a project's `repo_url` is blank/empty it would match any suffix. Add a `Project.repo_url != ''` guard in a follow-up.

## Learnings & Issues

### Sibling-merge conflict resolution worked as designed

T-407 merged first; T-409 hit `DIRTY` mergeStateStatus when its codex round 4 returned `:pass:`. The auto-merge gate's `pr_dirty` branch correctly held the merge, the agent merged `origin/main`, resolved `schemas.py`, pushed; round 5 found additional integration issues exposed by the merge (T-407's `outcome` column wasn't yet projected into the codex status state machine). All addressed before human merge.

### Dual Alembic heads guard

Round 5 CRITICAL flagged dual heads — T-407 and T-409 both added migrations independently. The fix linearised T-409's migration off T-407's revision (`479ae109c254 → b2c3d4e5f6a1`). The migration-validator subagent should already catch this; if it didn't, T-407+T-409 expose a gap. Worth verifying the validator runs on every migration-touching PR.

### Quality gate

`make quality` on `main` after the merge passed.

### Routing

- The `shared_pr_urls_in_project` fallback pattern (route duplicate-pr_url tasks to legacy projection rather than blocking) is a useful defensive idiom — safer than introducing a new write-time guard whose breakage is silent. Documented in T-409's repository.py; no separate invariants.md entry needed.
- `find_projects_by_repo` blank-repo_url gap: filed in residual TODOs above. If it bites, file a task; otherwise leave alone.

## State After This Wave

- The board now surfaces 7 codex states; the PR #314-class stall would render as `codex stale` within seconds.
- T-407's `outcome='db_error'` flows through to a red `codex failed` badge.
- T-408 still in flight (PR #317). After it merges, the structured-events log story will line up 1:1 with the badge state machine.
