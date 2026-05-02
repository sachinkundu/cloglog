# Wave: t339-t305-close-tab-webhook (2026-05-02)

Two parallel single-task worktrees under feature **F-32 Worktree Close-off**, both shipped via cooperative shutdown. Wave-level close-off rows backfilled manually (T-379, T-380) because the launch SKILL ran `on-worktree-create.sh` before `register_agent`, leaving the original `create_close_off_task` calls 404'd — root cause filed as **T-378 (expedite)**.

## Worktrees in this wave

| Worktree | PR | Shutdown path | Commits | Files changed |
|---|---|---|---|---|
| wt-t339-close-tab-fix | [#291](https://github.com/sachinkundu/cloglog/pull/291) | cooperative | 1 squash | 7 |
| wt-t305-webhook-routing | [#292](https://github.com/sachinkundu/cloglog/pull/292) | cooperative | 1 squash | 5 |

## T-339 — Bug: close-wave/launch close-tab logic kills the focused tab

*From `wt-t339-close-tab-fix/shutdown-artifacts/work-log.md`*

PR: https://github.com/sachinkundu/cloglog/pull/291 — merged 2026-05-02T15:28:21Z

### What shipped

A guarded helper `plugins/cloglog/hooks/lib/close-zellij-tab.sh` that all zellij tab teardown call sites now route through. The helper resolves the target tab id by name, reads the focused tab id from `current-tab-info`, and refuses (exit 2) if they match — eliminating the class of bug where `query-tab-names` paired with a bare `close-tab` would kill the supervisor's own tab. Pinned by 9 tests in `tests/plugins/test_close_tab_safety.py`, wired into `make invariants`, documented in `docs/invariants.md`.

### Files touched

- `plugins/cloglog/hooks/lib/close-zellij-tab.sh` (new) — guarded helper.
- `plugins/cloglog/hooks/worktree-remove.sh` — route through helper, hard-error on exit 2.
- `plugins/cloglog/skills/close-wave/SKILL.md` — Step 5c rewrites bare `close-tab` block to call the helper.
- `plugins/cloglog/skills/reconcile/SKILL.md` — teardown section ditto.
- `tests/plugins/test_close_tab_safety.py` (new) — 9-test pin (static + runtime).
- `Makefile` — added new pin to `make invariants`.
- `docs/invariants.md` — added invariant entry "Zellij tab teardown must go through `close-zellij-tab.sh`".

### Decisions

- **One helper, three call sites** rather than inlining the guard at each site. Avoids drift; the static regex pin (`zellij action close-tab` not followed by `-`) catches a fourth call site copying the pattern wrong.
- **Use `close-tab --tab-id <id>`, not `close-tab-by-id <id>`.** `worktree-remove.sh` already used the `--tab-id` form in production — consistency over the marginally cleaner alternative.
- **Hard-error on exit 2** at every call site. The previous design silently swallowed teardown failures (`|| true`), which is exactly how the bug went unnoticed for so long.
- **Pin checks both static AND runtime regression modes.** Static regex catches a future bare `close-tab`; runtime smoke test with a fake `zellij` shim catches decay in the helper guard logic itself.
- **Did NOT touch `agent-shutdown.sh`** — line 144 reference is a comment about historical T-217 hook-skipping behaviour, not a call site.

### Review findings + resolutions

Codex (single session) returned `:pass:` with no requested changes. CI passed (`ci`, `init-smoke`, `e2e-browser` all green). No human review requested before merge.

### Learnings (from agent)

- **`zellij action close-tab` takes no positional argument.** It closes the *focused* tab. Pairing `query-tab-names` (which returns names) with a bare `close-tab` is a category error — the names go nowhere. To target a tab by name, you must `list-tabs` (gets stable TAB_IDs by name), then `close-tab --tab-id <N>` or `close-tab-by-id <N>`. Same shape applies to `go-to-tab` (positional index) vs `go-to-tab-name` (positional name) vs `go-to-tab-by-id` (positional stable id) — three distinct subcommands.
- **Silent `|| true` at teardown sites hides this whole class of bug.** Hard-error on exit 2 is the right shape — supervisor death is loud.
- **The regression mode for skill-file rules is the bare command, not the named alternative.** Pin tests should grep for the dangerous shape and assert its absence, NOT just assert the safe shape's presence.

### Residual TODOs

(none)

## T-305 — Webhook routing for main-agent PRs

*From `wt-t305-webhook-routing/shutdown-artifacts/work-log.md`*

PR: https://github.com/sachinkundu/cloglog/pull/292 — merged 2026-05-02T16:03:46Z

### What shipped

PR #231 (2026-04-26) shipped a codex review that never reached the main agent's inbox. Three webhook resolver drop branches (no project for repo, no `role='main'` worktree + no env-var fallback, non-main event with no match) plus the close-off-task creation route's "no main agent at write time" branch were all silent — backend logs offered zero signal to diagnose. PR #292 makes every silent-drop signature visible:

- `src/gateway/webhook_consumers.py::_resolve_agent` emits `logger.warning` on the two diagnostic-worth drops (no project for repo, no `role='main'` + no env-var fallback) and `logger.debug` on the deliberate non-main-agent drop. The handler's existing per-event debug line is preserved as a trace.
- `src/agent/routes.py::create_close_off_task` emits `logger.warning` when the persisted close-off task lands `worktree_id=NULL`. The warning text branches on resolver outcome **first**, then env-var state — so the operator's remedy step matches the actual cause.
  - `main_agent_worktree_id is not None` but `task.worktree_id is None` → idempotent no-backfill (existing row was unassigned and the service path doesn't re-assign on retry). Remedy: reassign with `mcp__cloglog__assign_task` or PATCH.
  - `main_agent_worktree_id is None` and `main_agent_inbox_path` unset → nothing registered. Remedy: `/cloglog setup` or backfill `worktrees.role`.
  - `main_agent_worktree_id is None` and `main_agent_inbox_path` configured → env var misrouted. Remedy: `/cloglog setup` or fix the env var.

The audit verified that `BoardService.create_close_off_task` does pass `main_agent_worktree_id` through to the task row when present, and `BoardRepository.get_tasks_for_worktree` filters only by `worktree_id` (no status filter excludes backlog close-offs). The PR #231 bug was upstream of both — `get_main_agent_worktree` returning `None` at close-off-create time, leaving the task unassigned and silent.

### Files touched

- `src/gateway/webhook_consumers.py` — diagnostic warnings on the two `_resolve_agent` drop branches; debug line on the deliberate non-main drop.
- `src/agent/routes.py` — module-level `logger`, `logger.warning` after `BoardService.create_close_off_task`, gated on persisted `task.worktree_id`, branched on resolver outcome.
- `tests/agent/test_close_off_task.py` — three new pin tests:
  - `test_close_off_task_surfaces_in_main_agent_get_tasks` — register main + create close-off + GET `/api/v1/agents/{main_wt_id}/tasks`; assert close-off appears with status=backlog.
  - `test_resume_does_not_warn_when_task_already_assigned` — first call assigns; break role + env-var; resume returns `created=false` with NO `"is unassigned"` warning.
  - `test_warning_diagnoses_idempotent_no_backfill_after_setup` — unassigned create → register main → retry hits idempotent path → assert warning names the no-backfill cause and does NOT emit the env-var diagnostic.
  - `test_unassigned_warning_distinguishes_inbox_path_configured` — configured-but-misrouted env-var case must emit the distinct "does not point at a registered worktree" message.
- `tests/gateway/test_webhook_consumers.py` — strengthened `test_resolver_returns_none_when_no_main_agent_registered` to assert the silent-drop signature on PR #231 cannot recur without a one-grep `Webhook drop` warning.
- `docs/demos/wt-t305-webhook-routing/exemption.md` — classifier exemption (logging-only diff; no router/decorator/schema changes).

### Decisions

- **Warning gates on persisted `task.worktree_id`, not per-call resolver state** — codex round 1 caught that the original implementation would emit false-positive "is unassigned" diagnostics on legitimate idempotent resume calls. The endpoint is documented idempotent, so the only truthful signal is the persisted state.
- **Warning text branches on resolver outcome first, env-var state second** — codex round 2 caught that the previous text-only branching produced a misleading "configured but does not point at a registered worktree" diagnostic in the operator-runs-`/cloglog setup`-then-retries scenario. The idempotent service path returns the existing unassigned row WITHOUT backfilling `worktree_id`, so resolver-now-resolves + persisted-still-unassigned is its own distinct cause requiring a distinct remedy.
- **No behavioural change in production code paths.** Control flow, response shapes, DB writes, and webhook fan-out are unchanged. The PR is observability-only.

### Review findings + resolutions

- **Codex session 1/5 [HIGH]** — `src/agent/routes.py:371`: warning emitted before `BoardService.create_close_off_task` returns. Fix: move warning after the service call; gate on `task.worktree_id is None`. Pin: `test_resume_does_not_warn_when_task_already_assigned`.
- **Codex session 2/5 [HIGH]** — `src/agent/routes.py:388`: warning text infers cause only from `main_agent_inbox_path`, mis-blaming the env var when `/cloglog setup`-then-retry leaves the existing row unassigned. Fix: branch on resolver outcome first; introduce idempotent-no-backfill cause + remedy. Pin: `test_warning_diagnoses_idempotent_no_backfill_after_setup`.
- **Codex session 3/5** — `:pass:`. Codex traced the full diff plus supporting code, ran the targeted pytest suite and `scripts/check-demo.sh`, both passed.

### Learnings (from agent)

- **Idempotent endpoints + diagnostic warnings = gate on persisted state, not per-call resolver state.** Otherwise a legitimate retry where one of the inputs has since changed produces a false diagnostic. Extends the silent-failure invariant set: when adding observability to an idempotent code path, the warning's truth value must survive a retry where the inputs flicker.
- **Branching warning text on a single derived input** (e.g., `settings.main_agent_inbox_path`) is fragile when the persisted state can be the result of a different code path. Branch on resolver outcome first, then on the input state — three distinct causes need three distinct remedies, otherwise the operator's next debug step is wrong.
- **The `pr_merged` webhook fans out only to the merging worktree's own inbox.** Operator-driven close-off-task hooks that fire from the main agent (e.g., `on-worktree-create.sh`) need an explicit `pr_merged_notification` write to the project-root inbox so the supervisor sees the close-off-PR merge — same pattern T-262 codified for cross-worktree visibility.

### Residual TODOs

(none)

## Wave-level learnings

Routed (Step 11):

- **Launch SKILL ordering bug — register_agent must precede on-worktree-create.sh.** Filed as **T-378 (expedite)**. The script silently WARNs and continues on a 404, hiding the gap until close-wave fails Step 1.5 much later. Fix: reorder Step 4 in `plugins/cloglog/skills/launch/SKILL.md`, change WARN to fail-loud in `.cloglog/on-worktree-create.sh`, add a pin asserting the call order.
- **CI fires on every PR push — switch to fire only on codex finalization (`:pass` or 5/5 turns).** Filed as **T-377**. Both `ci.yml` and `init-smoke.yml` use `pull_request: types: [opened, synchronize, reopened]` (default). Empirical observation: runs almost always pass; the per-push gate is noisy and expensive vs. one run after codex terminal state.

Both routed-as-tasks rather than baked into this PR.

## Shutdown summary

| Worktree | PR | Tier-1 deadline | Path | Notes |
|---|---|---|---|---|
| wt-t339-close-tab-fix | #291 | self-initiated on `pr_merged` | cooperative | agent unregistered 2026-05-02T15:29:29Z; `tasks_completed: [T-339]` |
| wt-t305-webhook-routing | #292 | self-initiated on `pr_merged` | cooperative | agent unregistered 2026-05-02T16:05:15Z; `tasks_completed: [T-305]` |

## State after this wave

- Zellij tab teardown is now guarded (T-339); supervisor's tab cannot be killed by close-wave/reconcile teardown paths — pin tests block regression.
- Webhook silent-drop signatures from PR #231 are now visible via `WARNING` logs (T-305) — operator can grep `Webhook drop` to diagnose missing inbox events without reading source.
- Both worktrees + branches removed; remote branches deleted; close-off rows T-379 + T-380 will move to `review` with this PR.
- Outstanding follow-ups: T-377 (CI trigger narrowing), T-378 (launch SKILL ordering bug).
