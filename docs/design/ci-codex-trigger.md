# CI on codex finalization (T-377)

## Problem

Until T-377, `.github/workflows/ci.yml` triggered on the default
`pull_request` event types — `opened`, `synchronize`, `reopened`. The
codex reviewer iterates a PR by pushing patches up to `codex_max_turns`
(currently 5) per session, and the agent under review may also push
patches as it responds to findings. Every push fired `synchronize` and
spun up a fresh CI runner that:

1. Ran the full backend + frontend + MCP + contract suite against an
   intermediate state codex was about to obsolete a few minutes later.
2. Burned 4–8 minutes of runner time per push for a signal nobody
   acted on until codex finalized.
3. Cancelled the previous in-flight CI run via the `cancel-in-progress`
   concurrency rule, often killing it after it had already paid the
   container-startup cost.

`init-smoke.yml` (the plugin-portability gate) intentionally runs on
every PR push and is *not* affected — it must keep firing on every push
so a downstream-breaking change can't slip past while waiting on codex.

## Design

CI runs only when the codex reviewer reaches a terminal state for the
current head SHA — defined as either:

- **Consensus** — `verdict == "approve"` with no severe findings, or
  `status == "no_further_concerns"`, or no new findings vs. the prior
  turn's findings (the `_reached_consensus` predicate in
  `src/gateway/review_loop.py`).
- **Exhaustion** — all `codex_max_turns` ran without consensus, with no
  webhook-re-fire-retryable failure (`post_failed`) on any turn.

`src/gateway/review_loop.py::dispatch_ci_after_codex` issues a
`repository_dispatch` event with `event_type: codex-finalized` and a
`client_payload` carrying the PR's head SHA and number. `ci.yml`
declares:

```yaml
on:
  pull_request:
    types: [opened, reopened, ready_for_review]   # not synchronize
    branches: [main]
    paths: …
  repository_dispatch:
    types: [codex-finalized]
```

The `pull_request` types narrow to PR-creation events so a brand-new
PR still gets a fast first CI signal — without that, a docs-broken or
test-broken PR would sit untested for the multi-minute codex window
before any feedback reached the human reviewer.

### Why repository_dispatch (not workflow_dispatch)

`workflow_dispatch` requires the `actions: write` GitHub App
permission. The cloglog Claude bot only carries
`{contents, pull_requests, issues, workflows}: write`
(`scripts/gh-app-token.py`). `repository_dispatch` requires
`contents: write` — already in the bot's grant. Expanding the App
permissions just to enable `workflow_dispatch` would be a security
regression for no benefit.

### Token choice

The dispatch is issued by the **Claude bot** (via
`get_github_app_token()`), not the codex-reviewer App. The
codex-reviewer App is intentionally read-only (`contents: read`) so it
cannot push to branches or trigger workflows. Routing the dispatch
through the Claude bot keeps the reviewer's permissions tight while
still letting the review pipeline trigger CI.

### Check-run mirroring

When triggered by `repository_dispatch`, a workflow run's
auto-attached check runs land on `github.sha` — which for that event
type is the default branch's HEAD, *not* the PR's head SHA. The
auto-merge gate (`plugins/cloglog/scripts/auto_merge_gate.py`) reads
`gh pr checks` on the PR's head SHA, so without explicit mirroring it
would never see the CI result and would fall through to the "empty =
green" default — letting a CI-failed PR merge.

Each job (`ci`, `e2e-browser`) ends with a step gated on
`github.event_name == 'repository_dispatch'` that POSTs a check_run
with `head_sha = client_payload.head_sha` and `conclusion =
job.status`. The auto-attached default-branch checks become harmless
noise; the mirrored head_sha checks are what branch protection and the
auto-merge gate consume.

### Idempotency

`ReviewLoop.run()` has three early-return paths that already
short-circuit before re-running a finalized stage:

- Any prior turn with `consensus_reached = True` → the original firing
  dispatched; the re-fire returns immediately without entering the
  loop.
- `start_turn > max_turns` (all slots filled) → same.
- Stage A (opencode) → no dispatcher is wired; the hook is a no-op.

Within a single firing the dispatch runs at most once: it lives after
the loop body, gated on either `consensus_reached` or `turns_used ==
max_turns AND no post_failed in errors`. A `post_failed` mid-loop
break does *not* dispatch — the failed turn is rerunnable on webhook
re-fire (`_compute_next_turn` resumes failed rows), and dispatching
now would let CI race a not-yet-final review.

### Failure handling

`dispatch_ci_after_codex` swallows HTTP errors after logging — a
missed dispatch surfaces as a PR with no post-finalization CI signal,
recoverable by either (a) the operator pushing a no-op commit on the
branch (which fires a fresh review pipeline whose terminal state
re-dispatches), or (b) re-issuing the dispatch by hand. The hook does
not raise into `ReviewLoop.run()` because the webhook handler should
not 500 on a CI-trigger glitch — the review itself succeeded.

## Pins

- `tests/plugins/test_ci_workflow_codex_finalized_trigger.py` — YAML
  shape: `synchronize` absent, `repository_dispatch: codex-finalized`
  present, both jobs check out `client_payload.head_sha`, mirror step
  POSTs a head_sha check_run.
- `tests/gateway/test_review_loop_t377_ci_dispatch.py` — firing rule:
  fires on consensus / exhaustion / final-turn timeout; does not fire
  on opencode / post_failed / re-fired-already-finalized runs.
- `tests/plugins/test_init_smoke_ci_workflow.py` — unchanged;
  `init-smoke.yml` keeps `pull_request` (no `paths:` filter) so plugin
  portability stays decoupled from codex.

## Operator-visible changes

- A PR opened via `gh pr create` still gets CI immediately (PR-creation
  trigger).
- After the first push, no CI runs until codex finalizes — `gh pr
  checks --watch` will wait several minutes longer than before.
- Once codex finalizes, the workflow run appears under the
  default branch in the Actions UI (because `repository_dispatch` runs
  there) but the head_sha-mirrored check_runs are visible on the PR
  as `CI / ci` and `CI / e2e-browser`.
