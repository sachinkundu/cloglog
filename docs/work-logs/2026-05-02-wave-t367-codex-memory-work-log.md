# Wave: t367-codex-memory — work log

Date: 2026-05-02
Worktrees: `wt-t367-codex-memory`
PRs: #289

## Worktrees in this wave

### wt-t367-codex-memory

- **PR:** [#289 — feat(review): codex exhaustive single-pass + cross-push memory (T-367)](https://github.com/sachinkundu/cloglog/pull/289) — merged 2026-05-02T14:30:00Z (no codex review posted; codex CLI hit `REVIEW_TIMEOUT_SECONDS=300.0` twice on a ~1500-line diff and the TimeoutError branch silently logged-and-skipped — see follow-up T-374)
- **Branch:** `wt-t367-codex-memory` (base `origin/main` @ d23a5df)
- **Commits:** 1

```
582b2f5 feat(review): codex exhaustive single-pass + cross-push memory (T-367)
```

- **Files changed (17):**
  - `.github/codex/prompts/review.md`, `.github/codex/review-schema.json`, `.github/pull_request_template.md` (new)
  - `docs/demos/wt-t367-codex-memory/exemption.md` (new)
  - `docs/design/codex-exhaustive-review.md` (new)
  - `plugins/cloglog/skills/github-bot/SKILL.md`
  - `src/alembic/versions/1574708abb78_add_findings_and_learnings_to_pr_review_.py` (new)
  - `src/gateway/review_engine.py`, `src/gateway/review_loop.py`
  - `src/review/interfaces.py`, `src/review/models.py`, `src/review/repository.py`
  - `src/shared/config.py`
  - `tests/gateway/test_review_engine.py`, `tests/gateway/test_review_loop.py`, `tests/gateway/test_review_loop_t367_memory.py` (new)
  - `tests/review/test_repository.py`

#### Per-task work log (T-367) — from `work-log-T-367.md`

```
---
task: T-367
title: Codex reviewer — exhaustive first-pass + cross-session memory of prior findings
pr: https://github.com/sachinkundu/cloglog/pull/289
merged_at: 2026-05-02T14:30:00Z
---
```

##### What shipped

Codex review pipeline now reviews thoroughly on the first pass and remembers what it found across pushes, instead of stopping early on every webhook and rediscovering the same facts on each push.

Five orthogonal pieces, all in PR #289:

1. **PR template** (`.github/pull_request_template.md`) + `cloglog:github-bot` skill update — agents fill *Feature / Task / What changed / Test or demo / Out of scope* sections; the body is injected verbatim into the codex prompt under "What this PR is doing." Soft enforcement (skill instruction, no CI gate).
2. **Codex prompt** (`.github/codex/prompts/review.md`) — paired sections: "Be exhaustive — but only on real findings" (counters the consistent 2–3 finding shape) and "Concentrate on what *could* happen, not what *might* happen" (counters speculative findings the implementing LLM would otherwise spend tokens fixing).
3. **One codex turn per webhook** (`codex_max_turns: 2 → 1`). Lifetime cap of 5 reviews per PR stays via existing `MAX_REVIEWS_PER_PR=5`. Turns are now paced by author pushes, not stacked in one webhook handler.
4. **Cross-push memory** — additive Alembic migration adds `findings_json` + `learnings_json` JSONB columns on `pr_review_turns`. Two new `IReviewTurnRegistry` methods (`record_findings_and_learnings`, PR-scoped `prior_findings_and_learnings`). Codex prompt receives a "Prior review history" preamble before the diff with topic-deduped learnings (last-write-wins on note).
5. **Codex review schema** — additive `learnings` array (required-but-may-be-empty per OpenAI Structured Outputs rule).

Design spec: `docs/design/codex-exhaustive-review.md`.

##### Decisions

- **Storage on `pr_review_turns` JSONB columns, not a new table.** Same key shape, same context owner. Trade-off: querying findings by attribute (e.g., "all P3 codex findings on closed PRs") would prefer a separate `pr_review_findings` table — flagged in the spec, deferred.
- **PR-scoped memory, not commit-scoped.** A fix-up commit changes `head_sha` but the prior findings/learnings are still the relevant memory.
- **Soft cross-push memory (DB rows + prompt replay), not hot/persistent codex daemon.** Operator confirmed soft is fine. Each codex turn is still a fresh subprocess; persistence is via DB and prompt assembly.
- **One codex turn per webhook, not 1-of-5 stacked.** Operator catch during brainstorming: codex doesn't see new diff between back-to-back turns inside one webhook, so turn 2 was always re-emitting the same findings and tripping the consensus subset rule.
- **Topic-based dedup, last-write-wins on note.** Codex picks the topic string. Slight wording drift won't dedupe — accepted noise for v1.
- **Author response wiring deferred.** Spec §3.4 envisions `gh api .../reviews/M/comments` per prior turn; renderer currently emits `Author response: (not fetched)` placeholders. Stable shape for future fetch.
- **PR template enforcement is soft.** No CI gate.
- **`learnings` field is required-may-be-empty in the schema** (OpenAI Structured Outputs strictness).
- **"What *could* happen, not what *might* happen"** prompt section, mid-stream addition by operator. Counter-pressure to "be exhaustive."

##### Review findings + resolutions

PR #289 was approved and merged with **no codex review posted at all** — see Learnings & Issues below. Pre-PR `make quality` was green (1187 passed / 1 skipped / 1 xfailed @ 88.09% coverage).

##### Learnings (carried forward)

- `Reviewer.run` is a stable protocol surface; new cross-cutting prompt context lands as a new optional kwarg, ignored by `OpencodeReviewer`.
- `build_codex_prompt` is the only place that assembles the codex prompt — assembly-site drift would silently break cross-push memory.
- OpenAI Structured Outputs is strict about `required`. Every property must be in `required`; optionality is via `"type": ["<t>", "null"]`. Pinned by `test_codex_review_schema.py`.
- `pr_review_turns.findings_json IS NULL` distinguishes "complete_turn called but record_findings_and_learnings skipped" from "completed with empty findings array."
- `_StubLoop.run` signatures should be `**_kwargs` in any new sequencer-level test.

##### Residual TODOs (carried forward)

1. **Fetch + render author responses to prior codex findings.** Renderer placeholder is `Author response: (not fetched)`; spec §3.4.
2. **Diagnostic for early-stop cause** (spec §6) — verify the model is actually emitting longer reviews now.
3. **Hard PR-template enforcement** if soft enforcement leaks.
4. **Learnings dedup by semantic similarity** (currently topic-string-exact).
5. **Cross-PR codebase learnings** — today PR-scoped; cross-PR would need a project-keyed table.

## Shutdown summary

| Worktree | PR | Shutdown path | Notes |
|---|---|---|---|
| wt-t367-codex-memory | #289 | cooperative | Agent self-unregistered via `pr_merged` inbox event. Launcher + claude lingered after `unregister_agent` (T-352 in flight, second occurrence in this session — same fingerprint as wt-t371). Supervisor closed the zellij tab to clean up. |

## Learnings & Issues

### Codex review never posted on PR #289 — silent timeout

PR #289 (1548 additions, 26 deletions, 17 files) hit the hard-coded `REVIEW_TIMEOUT_SECONDS = 300.0` in `src/gateway/review_engine.py:62`. Prod log shows two timeouts (`opened` event + `synchronize` retry):

```
codex turn timeout after 300.0s (pr=289)
codex turn timeout after 300.0s (pr=289)
```

Logged at `src/gateway/review_loop.py:504` — visible *only* via prod log tail, not surfaced anywhere agents can see. Author and supervisor were both unaware codex had even tried.

**Filed as T-374** ("Scale codex review timeout by diff size + emit codex_review_timed_out event"). Two-part fix: (a) move the constant into `Settings` with three knobs (`base`, `per_kchar`, `max`) so big diffs get proportionally more time, capped at 900s; (b) emit a `codex_review_timed_out` inbox event so silence stops being indistinguishable from "in progress."

### Antisocial PR #15 — sibling F-36 issues surfaced during this session

Investigating PR #289's missing review uncovered antisocial PR #15 thrashing with **7 codex reviews under 3 session counters** (5/5 cap bypassed, verdicts flip-flopping `:warning: → :pass: → :warning:` within session 3). Two distinct bugs filed:

- **T-375** — codex posts multiple reviews under one session counter (intra-session duplication). Sessions 1, 2, 3 each posted 2–3 reviews. Hypothesis: concurrent `_review_pr` invocations race on the same `session_index`, or webhook re-delivery isn't idempotent.
- **T-376** — `MAX_REVIEWS_PER_PR=5` cap counts sessions, not posted reviews. Decision needed before code: should the cap be "5 posted reviews on the PR" (matches the constant's name and the user-visible runaway-loop signal) or "5 sessions" (and T-375 is the real fix)?

Both filed on F-36 alongside T-374; recovery path on antisocial side is operator-driven (manual auto-merge gate run from antisocial supervisor session — separate from this wave's scope).

### Lingering launcher (T-352) seen again

Same shape as wt-t371: agent emitted `agent_unregistered` cleanly, then the launcher + claude process did not exit on their own. Supervisor closed the zellij tab to reap them. Second occurrence in this session, both on a fresh-from-template launch — strong signal T-352 should be expedited.

## State After This Wave

- F-36 has T-374, T-375, T-376 newly filed, all flagged from this session's evidence (PR #289 timeout, PR #15 thrash). T-341 ("Codex re-trigger reliability") remains the older sibling.
- T-373 (`Close worktree wt-t367-codex-memory`) flows `in_progress → review (with this PR's url) → done` per the post-T-371 close-wave lifecycle.
- T-367 itself merged in `review` with `pr_merged=true`; user drags to done.
- `mcp-server/dist/` rebuilt by `make sync-mcp-dist` — tool surface unchanged, no broadcast.
