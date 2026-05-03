# Wave: T-377 CI Trigger (2026-05-02)

Single-worktree wave — `wt-t377-ci-trigger` ran T-377 in isolation while
`wt-codex-review-fixes` continues a separate codex-reviewer task bundle.

## Worktrees in this wave

| Worktree | Branch | PR | Tasks | Shutdown path |
|---|---|---|---|---|
| `wt-t377-ci-trigger` | `wt-t377-ci-trigger` | [#294](https://github.com/sachinkundu/cloglog/pull/294) | T-377 | tier-1 (`agent_unregistered` received) + tab-close to clear T-352 launcher residue |

## Shutdown summary

- **T-377 / PR #294** — agent emitted `agent_unregistered` cleanly at
  `2026-05-02T20:22:27+03:00` after PR merge. `tier-1` cooperative shutdown
  worked from the agent's side. Launcher + claude PIDs (1078293 / 1078313)
  lingered post-unregister — known regression T-352. Closed via
  `plugins/cloglog/hooks/lib/close-zellij-tab.sh wt-t377-ci-trigger`
  (rc=0); processes exited within 2s.
- **Close-off card**: T-383 backfilled via `create_close_off_task` after
  re-registering the worktree, because the launch SKILL fired
  `on-worktree-create.sh` before `register_agent` and the original
  bootstrap call returned 404 (T-378). Same gap T-339 / T-305 hit.

## What shipped (from `shutdown-artifacts/work-log-T-377.md`, T-377)

- `.github/workflows/ci.yml`: dropped `pull_request: synchronize`,
  narrowed to `[opened, reopened, ready_for_review]`, added
  `repository_dispatch: types: [codex-finalized]`. Both jobs check out
  `client_payload.head_sha` and POST a head_sha-scoped check_run via the
  Checks API so auto-merge gate / branch protection see CI status.
- `src/gateway/review_loop.py`: new `dispatch_ci_after_codex` helper using
  the Claude bot's `contents:write` token (codex-reviewer App is
  read-only). New optional `ci_dispatcher` argument to
  `ReviewLoop.__init__`; called once per (PR, head_sha) when stage B is
  terminal (consensus reached, OR `turns_used == max_turns` with no
  retryable failure in `outcome.errors`). Webhook re-fire short-circuits
  (`already_at_consensus`, `start_turn > max_turns`) skip dispatch.
- `src/gateway/review_engine.py`: wires `dispatch_ci_after_codex` into
  the codex `ReviewLoop` only — opencode (advisory) gets no dispatcher.
- `.github/workflows/init-smoke.yml`: extended pytest invocation to also
  run `tests/plugins/test_init_smoke_ci_workflow.py` and
  `tests/plugins/test_ci_workflow_codex_finalized_trigger.py`. Required
  because `repository_dispatch` runs ci.yml from the default branch, not
  the PR head — so a self-disabling workflow edit on a PR would never
  run its own pin tests against the modified workflow. Init-smoke
  remains on every PR push (no paths filter), so workflow YAML pins now
  ride that gate.
- `tests/gateway/test_review_loop_t377_ci_dispatch.py` (9 new tests),
  `tests/plugins/test_ci_workflow_codex_finalized_trigger.py` (6 new),
  `tests/plugins/test_init_smoke_ci_workflow.py` (extended) — full pin
  set for the new firing rule and workflow-shape invariants.
- `docs/design/ci-codex-trigger.md` — design doc.
- `CLAUDE.md` — CI section updated to reference the new flow.
- `docs/demos/wt-t377-ci-trigger/exemption.md` — classifier exemption
  (no_demo, internal CI plumbing).

### Codex review (1 round of fixes, both findings correct)

1. **`repository_dispatch` runs from default branch.** Self-disabling
   edits to ci.yml or init-smoke.yml could merge with no PR-branch CI
   signal under the new regime. **Fix:** route the workflow YAML pin
   tests through `init-smoke.yml`.
2. **`failed` is also retryable, not just `post_failed`.** A subprocess
   crash on the final allowed turn would have dispatched CI even though
   that turn is rerunnable. **Fix:** gate on `err.endswith(": failed")
   or "post_failed" in err`. New test
   `test_failed_turn_at_max_turns_does_not_fire`.

## Verification

- `make quality` (worktree side): green. 1225 passed / 1 skipped / 1
  xfail in 303s, coverage 87.97%, contract compliant, demo-check passed
  (exemption verified).
- 61 targeted tests (T-377 trigger pin × 6, T-377 dispatch pin × 9,
  init-smoke pin × 8, review_loop existing × 38) all passed.

## Residual TODOs / context for future tasks (from agent's own log)

- **Branch-protection rule names.** Mirror step posts check_runs named
  `CI / ci` and `CI / e2e-browser` on `head_sha`. If branch protection
  on `main` requires specific check names by ID, an operator-side
  protection-rule update is needed for those PRs to merge. Auto-merge
  gate's "empty checks list = green" semantics absorb this for now.
- **Codex-unavailable path is unmonitored.** When
  `self._codex_available=False`, stage B is skipped and no dispatch
  fires. CI then runs only on PR open. Acceptable for dev-only
  `codex_unavailable`; production has codex available. If a future
  production host loses codex, this surfaces as a PR with no
  post-creation CI signal.
- **`actions:write` permission expansion would simplify check-run
  semantics.** Going with `repository_dispatch` (`contents:write`,
  already granted) avoids expanding the App's permissions just to use
  `workflow_dispatch`. A future change wanting `workflow_dispatch`
  needs a separate PR plus an App-permission update.
- **`init-smoke.yml`'s scope is now partly mixed.** Originally the
  fresh-repo init gate; T-377 added two workflow-YAML pin files that
  aren't really about init. Pragmatic compromise — init-smoke is the
  always-on per-push gate; live with the slight scope creep.

## Learnings & integration issues

- **T-352 (launcher lingers after `unregister_agent`) reproduced.** Agent
  emitted `agent_unregistered` and finished its shutdown sequence, but
  the bash launcher + claude subprocess kept running until the zellij
  tab was closed. Documented behaviour, no new task — the existing T-352
  carries the fix. Close-wave Step 6's "rare, but possible if the agent
  hung after `unregister_agent`" is currently the load-bearing
  mitigation; it worked here.
- **T-378 (launch SKILL fires `on-worktree-create.sh` before
  `register_agent`) reproduced.** `on-worktree-create.sh` logged the 404
  for `create_close_off_task` ("Worktree not registered for this
  project: ... Call register_agent first") at worktree-bootstrap time;
  close-wave then had to re-register the (already-torn-down) worktree to
  call `create_close_off_task`. T-378 owns the launch-flow fix.
- **T-382 (cross-project credential resolution) filed earlier today.**
  Triggered by the antisocial-stale-worktree investigation; not
  relevant to T-377 itself but adjacent enough to call out.

## State after this wave

- `main` advanced from `346dc8c` to `a901e30` (10 files, +857 / −17).
- New CI trigger live on `main`. The next PR opened will exercise it.
- `wt-codex-review-fixes` worktree continues with T-374 in progress
  (T-375 / T-376 / T-381 queued for supervisor relaunch).
- T-377 status: `review` with PR merged; awaits user drag to `done`.
- T-383 (close-off): in_progress; will move to `review` with this wave's
  PR.
