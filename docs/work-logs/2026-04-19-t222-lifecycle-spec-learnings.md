# wt-f48-spec — learnings

**Date:** 2026-04-19
**Worktree:** `wt-f48-spec`

Things worth carrying forward for future spec/doc agents. Each entry is a
pattern, gotcha, or follow-up rather than a generic "what went well."

## Spec-writing patterns

- **Docs-only PRs still need a demo.** The `demo-check` step in `make
  quality` refuses to pass without a `docs/demos/<branch>/demo.md`. For a
  pure-spec PR the demo can be a Showboat structural proof — `wc`,
  `grep`, `sed` — that each required section of the doc exists and
  contains the expected language. That doubles as reviewable evidence
  (the reviewer can `uvx showboat verify` to confirm the doc hasn't
  drifted since submission) without needing a running server. See
  `docs/demos/wt-f48-spec/demo-script.sh` as a template.
- **`uvx showboat init` refuses to overwrite.** On a re-run of the demo
  script, the existing `demo.md` must be deleted first (`rm
  docs/demos/<branch>/demo.md`). This bit me once during the review-fix
  cycle; future docs-agents should bake the `rm` into the script idempotently.
- **Spec agents should still brainstorm — but skip the Q&A.** The
  `superpowers:brainstorming` skill is gated by project convention for
  creative work, but the worktree-agent rules say "never use interactive
  skills that ask questions." Reconciliation: invoke the skill to
  structure your decisions, treat the questions as self-directed, and
  commit decisions into the doc. User reviews via the PR, not a terminal
  dialog.

## Review-exchange patterns

- **cloglog-codex-reviewer[bot]'s first pass can fail silently.** One of
  the two reviews on PR #152 came back with "bwrap: loopback: Failed
  RTM_NEWADDR: Operation not permitted" — the reviewer's sandbox
  couldn't read any source files. It still posts a `COMMENTED` review
  event; the agent must read the body and classify it as non-actionable
  rather than assume the review has feedback. Suggested response:
  `add_task_note` documenting the infra failure, stay in review, wait
  for a follow-up review or the user.
- **Verify reviewer findings before pushing fixes.** Both of the bot's
  HIGH/MEDIUM findings were corroborated by `grep`/`Read` against the
  actual source files before I rewrote the spec. Treating the review as
  gospel would have been as wrong as dismissing it — the reviewer's
  interpretation of `src/agent/services.py:237` is load-bearing and
  worth checking directly.

## Shipped-code gotchas surfaced while writing the spec

- **Pre-existing worktrees inherit stale `shutdown-artifacts/`.** When I
  went to write this file, I found `wt-depgraph`'s 2026-04-05 stubs
  sitting there. This is exactly what T-242 is tracking ("Reset
  shutdown-artifacts/ on worktree create"). Noting it here as a live
  example.
- **Worktree `uv` env isn't synced at launch.** First `make quality`
  failed importing `respx` because the worktree hadn't run `uv sync
  --all-extras` since branching. Docs agents typically don't interact
  with the Python env; if a backend test touches a newly-introduced
  dev dependency, `make quality` breaks on a pure-docs PR. Worktree
  setup should sync — or the launch hook should — tracked implicitly
  under the worktree-hygiene follow-ups.
- **`.mcp.json` is a common inherited-dirty-state file.** The check
  between `localhost:8001` and `127.0.0.1:8001` flips depending on who
  ran last. The pre-PR file audit caught it; future agents should
  continue auditing this file specifically.

## Board / process observations

- **No auto `pr_merged` backfill on the second push.** `mark_pr_merged`
  is idempotent per the tool description, but I only received one
  `pr_merged` event even though the PR went through two pushes
  (original + fix). If a future flow depends on `pr_merged` firing
  multiple times, that assumption is wrong; it fires once per merge.
- **`report_artifact` silently doubles as a "plan persistence" gate.**
  Backend blocks downstream tasks until this is recorded. For docs-only
  flows that don't produce a PR (plan tasks), there is a dependency on
  the `skip_pr=True` pathway in `update_task_status` that the shipped
  runner doesn't currently exercise. Captured in the spec's Trigger B
  and in the T-NEW-b follow-up.
