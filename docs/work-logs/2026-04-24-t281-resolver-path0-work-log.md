# Work log — wt-t281-resolver-path0 (T-281)

**Wave:** single-worktree close (T-281 merged via PR #204; ad-hoc, not part of a numbered wave)
**Worktree:** wt-t281-resolver-path0 (worktree_id 5ca42a3f-39d1-48ac-bf3b-8158e79b1d37)
**PR:** [#204](https://github.com/sachinkundu/cloglog/pull/204) — feat(review): per-PR root resolver Path 0 + temp-dir SHA fallback (T-281)
**Started:** 2026-04-24 09:37 local
**Merged:** 2026-04-24 07:28 UTC
**Shutdown path:** cooperative (agent emitted `agent_unregistered` on its own; main agent received the event, then ran close-wave)

## Shutdown summary

| Worktree | PR | Shutdown path | Commits | Notes |
|---|---|---|---|---|
| wt-t281-resolver-path0 | #204 | cooperative | 1 | clean first-pass merge, codex `:pass:` turn 1/2 |

## What shipped (consolidated from shutdown-artifacts/work-log.md)

Per-PR review-root resolver extended with two new strategies:

- **Path 0 — `IWorktreeQuery.find_by_pr_url`**: follows the canonical `tasks.pr_url → task.worktree_id → worktrees.id` join (same chain `webhook_consumers._resolve_agent` uses for routing). The only path that resolves main-agent close-out PRs — `find_by_branch` misses because the main agent has no worktree row for the close-out branch. False-positive findings on PR #200 and PR #202 motivated this.
- **SHA-check + temp-dir fallback**: any candidate whose `git rev-parse HEAD` disagrees with `event.head_sha` triggers `git worktree add --detach <main_clone>/.cloglog/review-checkouts/<sha8>-<pr> <head_sha>`. `_review_pr` wraps stages A/B in `try/finally` so the disposable checkout is cleaned up via `git worktree remove --force` even when the reviewer raises. If temp-dir creation fails, falls through to the stale candidate with a `review_source_drift` warning.
- **`resolve_pr_review_root` now returns `PrReviewRoot`** (frozen dataclass: `path`, `is_temp`, `main_clone`) instead of a bare `Path`. Callers inspect `is_temp` to know whether cleanup is needed.

### Files touched
- `src/agent/interfaces.py` — extended `IWorktreeQuery` Protocol with `find_by_pr_url`
- `src/agent/services.py` — added `_WorktreeQueryAdapter.find_by_pr_url` composing `BoardRepository.find_task_by_pr_url_for_project` + `AgentRepository.get_worktree`; `make_worktree_query` now wires both repos
- `src/gateway/review_engine.py` — `PrReviewRoot` dataclass; refactored `resolve_pr_review_root` to Path 0 → Path 1 → host-fallback → SHA-check + temp-dir; added `_probe_git_head` / `_create_review_checkout` / `_remove_review_checkout` / `_git_worktree_{add,remove}` / `_git_fetch_branch` helpers; `_review_pr` now uses `try/finally` for cleanup
- `tests/agent/test_unit.py` — `TestFindWorktreeByPrUrl` (5 subtests)
- `tests/gateway/test_review_engine.py` — 6 new resolver cells + 2 cleanup-at-`_review_pr`-level tests + updates to 5 existing tests for the new `PrReviewRoot` return type
- `docs/design/two-stage-pr-review.md` §9 — rewrote for T-281 order + SHA-check policy table
- `docs/demos/wt-t281-resolver-path0/` — verify-safe demo: file-level greps + three standalone Python proofs

### Test delta
- Baseline (`origin/main`): 812 passed, 1 xfailed, coverage 89.64%
- Post-change: **824 passed** (+12), 1 xfailed, coverage 88.38%
- `make quality` fully green, `showboat verify` byte-exact on re-run

### Review summary
One codex round, turn 1/2, `:pass:` verdict, no findings, no inline comments, no human comments. CI green. Merged without revision. Codex reviewed against the pre-T-281 prod backend (T-278's resolver worldview) — expected per the "Prod runs pre-merge code" CLAUDE.md note; called out explicitly in the PR body.

## Decisions worth carrying forward

- **`PrReviewRoot` dataclass return type** chosen over tuple/context manager. Tuple loses self-documentation; context manager forces an `async with` shape callers may not want (e.g. `_review_pr`'s session-release happens before stages A/B). Dataclass with explicit `is_temp` forces every caller to acknowledge cleanup without forcing a control-flow shape.
- **Adapter composes Board + Agent repos**, Agent repo stays ORM-clean. `AgentRepository` never imports `src.board.models`; the join runs in the adapter via `BoardRepository.find_task_by_pr_url_for_project` + a second `AgentRepository.get_worktree` call. Two round-trips, but DDD boundary stays clean.
- **Temp-dir parent is `<main_clone>/.cloglog/review-checkouts/`**, not a system temp dir. Must be inside a repo git knows about so `git worktree add/remove` work without extra `-C` gymnastics. `.cloglog/` is already gitignored.
- **`_git_fetch_branch` as the retry knob** (not `_git_fetch_sha`) because `git fetch origin <sha>` requires `uploadpack.allowAnySHA1InWant` on the remote. Branch-fetch is simpler and covers the race-window case. External-fork PRs deliberately fall through to drift-warning — explicitly out of scope.

## Learnings & Issues (consolidated from shutdown-artifacts/learnings.md + this session)

Four candidate CLAUDE.md additions surfaced; the post-processor decides which actually land. Captured here as the inputs to that decision:

1. **Per-PR root resolver now has THREE strategies, not two.** CLAUDE.md note about `Path.cwd()` should be updated to mention the three-level chain (Path 0 pr_url → Path 1 branch → host fallback) and the SHA-check bypass. SHA-check + temp-dir branch is three-way coupled across `_create_review_checkout`, the cleanup path, and `PrReviewRoot.main_clone` — grep `_REVIEW_CHECKOUT_SUBDIR` and `PrReviewRoot.main_clone` together when editing.
2. **Protocol extensions need a stub-audit pass.** Adding `find_by_pr_url` to `IWorktreeQuery` broke five tests with `AttributeError` far from the Protocol definition because Protocols aren't runtime-checked. When extending an Agent/Gateway/Review OHS Protocol, `grep -rn "<ProtocolName>"` and update every stub. Prefer typed stub classes over MagicMocks for Protocol surfaces.
3. **Demo proof scripts load conftest-free** (already documented). T-281 followed the precedent: three standalone `proof_*.py` scripts under `docs/demos/wt-t281-resolver-path0/` with `sys.path.insert(0, repo_root)`. No pytest fixture, no DB connection, byte-exact `showboat verify`.
4. **`git fetch origin <sha>` needs server-side opt-in.** Use branch-fetch for in-host cases. External-fork PRs need `git fetch <fork-url> <sha>` or PR-ref fetching — see `docs/design/two-stage-pr-review.md` §9.6 for direction; not in scope for T-281.

Plus surfaced this session (T-284-adjacent, not from T-281 directly):

5. **Launch skill step 4c was using relative paths** — fixed in T-284 (PR #203). Pin test backstops it.
6. **MCP server caches a single `agentToken`** — main agent's token gets clobbered when `register_agent` runs for a worktree on the same MCP server. Filed as T-285.
7. **`delete_project` route has no auth Depends** — same shape as PR #191 / T-258. Filed as T-286.

## State After This Wave

- **T-281**: shipped (PR #204 merged); resolver Path 0 + SHA-check + temp-dir checkout in production code path on `origin/main`.
- **T-284**: shipped (PR #203 merged); launch skill 4c uses absolute paths; pin test catches relative-path / `cd` regressions.
- **T-285**: filed for MCP single-`agentToken` cache fix.
- **T-286**: filed for `delete_project` route auth Depends.
- Worktree `wt-t281-resolver-path0` torn down; branch deleted locally and on remote; DB `cloglog_wt_t281_resolver_path0` dropped; close-off task T-282 marked complete.

