# Work log — 2026-05-04 — t424-codex-exhausted-badge

Single-worktree wave. Closes T-424 (PR #322 merged 2026-05-04T16:59:11Z).

## Worktree summary

| Worktree | Tasks | PR | Shutdown path | Files changed | Commits |
|----------|-------|----|----|--------------|---------|
| wt-t424-codex-exhausted-badge | T-424 | #322 | cooperative tier 1 (agent emitted `agent_unregistered` at 2026-05-04T20:00:20+03:00) | 7 | 4 |

## Shutdown summary

- Cooperative shutdown succeeded (board state, work logs, inbox event all clean).
- **Post-unregister regression detected** — claude session pid 1133029 and launcher pid 1133009 survived `mcp__cloglog__unregister_agent`; `/tmp/agent-shutdown-debug.log` shows zero entries for `wt-t424-codex` (last entry 19:41:32, ~20 min before the unregister). T-352's `exit-on-unregister.sh` PostToolUse hook either did not fire or resolved the wrong claude pid. Filed as **T-428** (related to T-390). Artifacts captured at `/tmp/close-wave-t424-bug-artifacts/`. Tab closed via `close-zellij-tab.sh` helper; no `kill -9` used.

## What shipped

(from `shutdown-artifacts/work-log-T-424.md`, inlined verbatim)

Fixed the board's EXHAUSTED badge so it gates on the PR-wide `MAX_REVIEWS_PER_PR=5` cap (distinct posted `session_index` count) instead of the per-session `codex_max_turns` (default 1). Pre-fix, a single non-consensus codex turn flipped the badge to EXHAUSTED even though four more review sessions were still permitted.

### Files touched (T-424)

- `src/review/interfaces.py` — added `MAX_REVIEWS_PER_PR: Final[int] = 5`. Extended `IReviewTurnRegistry.codex_status_by_pr` Protocol with `max_pr_sessions: int`.
- `src/review/repository.py` — `_derive_codex_status` now computes `posted_sessions` and gates EXHAUSTED on the PR-wide count at two points (round-2 STALE→EXHAUSTED override on post-cap pushes; main predicate).
- `src/gateway/review_engine.py` — re-imports `MAX_REVIEWS_PER_PR` for back-compat.
- `src/board/routes.py` — passes `max_pr_sessions=MAX_REVIEWS_PER_PR` into `codex_status_by_pr`.
- `tests/board/test_codex_status_projection.py` — five new pin tests covering: PROGRESS at single session, EXHAUSTED at five sessions, NULL legacy rows ignored, STALE→EXHAUSTED override on old SHA, STALE preserved below cap. Replaced `test_exhausted_max_turns_no_consensus`.
- `tests/board/test_board_review_boundary.py` — boundary contract requires `max_pr_sessions`.
- `docs/demos/wt-t424-codex-exhausted-badge/{demo-script.sh, demo.md}` — Showboat demo (4 scenarios).

### Codex review history

- **Round 1 (HIGH)** addressed in `d6c1c14` (STALE-after-cap gap).
- **Round 2 (CRITICAL)** disregarded per operator direction — historical `docs/demos/wt-t227-review-cap/` is frozen-artifact, not updated when refactoring shared symbols. Empty nudge commit `4b850a0` woke codex after reply-only response.
- **Round 3 (HIGH)** re-flagged the same disregarded round-2 finding. No action — operator merged.

### Test report

- 1459 passed, 1 skipped, 1 xfailed (matches main baseline). Coverage 88.69%. Lint, types, contract, demo all green.

## Learnings & Issues

### Workflow learning — empty-nudge after reply-only PR comments

When the agent replies to a PR comment without a code change (e.g., disregarding a codex finding per operator direction), it must follow with `git commit --allow-empty -m "noop: re-run codex after operator disregard"` + push. Codex only re-fires on `synchronize` webhooks; comments alone leave the previous round's findings as the latest review and `repository_dispatch: codex-finalized` never dispatches, blocking ci.yml.

**Routed to** `plugins/cloglog/skills/github-bot/SKILL.md` `issue_comment` handler (commit `0a2e77c`).

### Workflow learning — historical demos are frozen artifacts

When refactoring shared symbols (e.g., moving a `Final[int]` constant between modules), do NOT update prior worktrees' `docs/demos/` files even if they grep for the old location. Each demo is a frozen point-in-time artifact of the PR that produced it. Codex will flag this as a regression; respond by disregarding (with empty-nudge per the rule above).

**Already encoded** in operator memory; no SKILL change needed — the disregard is a per-PR judgment, not a structural rule.

### Bug — surviving claude post-unregister (T-428)

Repeat of T-352-class regression. Filed as T-428 with full evidence in `/tmp/close-wave-t424-bug-artifacts/`. Related to T-390 (already filed). Until T-428 ships, every close-wave will need to fall back to closing the zellij tab via `close-zellij-tab.sh` after Step 6 detects the surviving claude.

## State after this wave

- **Codex EXHAUSTED gating** now reflects PR-wide review count, not per-session turns. Five distinct posted sessions are the cap; below the cap, the badge surfaces PROGRESS / IDLE / STALE as appropriate.
- **Empty-nudge after reply-only comments** is now a documented agent rule in the github-bot SKILL.
- **One open regression**: T-428 (post-unregister claude survival) — every close-wave will detect it until fixed.

## Residual TODOs

- **T-428** — investigate exit-on-unregister hook firing; pin test that `pgrep -af <wt-path>` is empty within 10s of `unregister_agent`.
- **Out-of-scope cosmetic**: `CodexProgress.max_turns` still renders per-session count in the inline `codex N/M` badge; UX pass could swap to PR-wide ratio.
- **Out-of-scope tunable**: `MAX_REVIEWS_PER_PR` is `Final[int] = 5`; promotion to a `Settings` field for per-host tuning was deferred by the task spec.
