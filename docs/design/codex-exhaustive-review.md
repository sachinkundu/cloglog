# Codex reviewer: exhaustive first-pass + cross-PR-life memory — design spec

> **Task:** T-367 on the board. Extends the codex stage of the two-stage PR
> review pipeline (`docs/design/two-stage-pr-review.md`). The opencode stage
> is untouched — it was tried and is no longer used in practice; that decision
> is out of scope for this task.

## 1. Problem

The codex reviewer today has three observable failure modes that compound:

1. **Codex stops early.** Reviews are consistently 2–3 findings regardless of
   diff size. The findings it does produce are deep and correct (architectural,
   contract, invariant problems — not style nits), but they look like the
   *first 2–3* of a longer list rather than the full set. Each early stop
   forces another push-and-review cycle for issues codex could have caught
   in one pass.
2. **Codex runs without context a human reviewer would have.** It receives
   the diff, `CLAUDE.md`, and the running review/inline-comment history scoped
   to the current commit SHA. It does **not** receive the PR description, the
   board task definition that motivated the diff, the parent feature, or any
   of Claude's reply comments on prior review threads. PR bodies authored by
   implementing agents today often omit "what was implemented," so the diff
   is reviewed essentially blind to intent.
3. **Codex re-derives everything every push.** Each `pull_request.synchronize`
   webhook spawns a fresh codex subprocess that re-reads the same source
   files, re-discovers the same architectural patterns, and may re-flag
   findings that Claude has already addressed in conversation. Token cost is
   wasted on rediscovery; review quality degrades because codex doesn't know
   which prior findings are now resolved.

## 2. Out of scope

- Opencode (`gemma4:e4b`) stage. Untouched. The two-stage sequencer keeps
  its current shape; opencode's per-webhook 5-turn loop is unchanged.
- Hot/persistent codex daemons. Every codex turn remains a fresh subprocess
  invocation. Memory is carried in **persisted state replayed into the next
  turn's prompt**, not in a long-lived process.
- MCP access for the codex subprocess. Codex stays MCP-less; everything it
  needs about the board is pre-bundled into the prompt by the backend.
- CI status, GitHub Checks API integration, or any reviewer-routing change.
- Hard enforcement of the PR template (CI gate, blocking check). Soft
  instruction only for v1.

## 3. Deliverables

Four orthogonal pieces, each independently verifiable:

### 3.1 PR template (soft enforcement)

**What:** `.github/pull_request_template.md` with sections:

```
## Feature
F-NN — title

## Task
T-NNN — title

## What changed
<implementing agent's narrative — what the diff does and why>

## Test or demo
<demo path, test additions, or "auto-exempt" rationale>

## Out of scope
<what this PR deliberately does not address>
```

Plus a one-paragraph addition to the `cloglog:github-bot` skill (or
whichever skill owns `gh pr create` for agents) instructing the implementing
agent to fill every section before opening the PR.

**Why soft:** the implementing agents are inside our workflow control; a
written instruction in the skill is enough. A CI gate adds friction to
human-authored PRs (operator-authored hotfixes, dependency bumps) for no
clear benefit. If skipped sections become a recurring problem in practice,
revisit with a hard gate.

**Why this matters for codex:** with the template filled, the PR body itself
carries `T-NNN` + `F-NN` + intent. The backend extracts these in §3.3 to
inject board context; codex *also* receives the body verbatim as part of
the review prompt, so even without backend extraction codex sees the
human-equivalent context.

### 3.2 Exhaustive single-pass codex

**Diagnostic step (must run before any "fix").** The early-stop has at
least four plausible causes; we don't know which is dominant:

- (a) An OpenAI Codex CLI flag (`--max-tokens` / `--max-output-tokens` /
  reasoning-effort cap) implicitly throttling output length.
- (b) The model self-rationing inside the response — emitting 2–3 findings
  because that's what feels "polite" review-output length absent stronger
  prompt direction.
- (c) The consensus predicate `(b) empty-diff` (per
  `docs/design/two-stage-pr-review.md` §1.1) firing on turn 2 of the *current*
  per-webhook 2-turn loop because turn-2 findings naturally overlap turn-1
  on an unchanged diff. This stops the loop *before* codex elaborates; the
  "2–3 findings" is then the turn-1 output.
- (d) The review schema (`.github/codex/review-schema.json`) silently
  truncating: it has `minLength: 1` on `body` but no minimum on the
  `findings` array, and we don't know whether the codex CLI's JSON-mode
  output buffer truncates a long array.

The implementer of this spec MUST run a one-shot diagnostic pass first
(detailed in §6) and pick the fix(es) the diagnostic indicts. The fix
may be a CLI flag, a prompt change, a schema change, or all three.

**Prompt change (independent of diagnostic outcome).** Append to
`.github/codex/prompts/review.md` two paired sections:

1. **"Be exhaustive — but only on real findings."** Tells codex to enumerate
   every concern, not curate down to a short list, not consolidate similar
   findings. Counters the consistently-2-3 shape today.

2. **"Concentrate on what *could* happen, not what *might* happen."** The
   counter-pressure to (1). Author of the diff is another LLM; it will fix
   every finding faithfully. Theoretical/speculative findings ("in principle
   an attacker could…", "a future extension might…", "this race window
   exists at microsecond scale") cause Claude to spend real tokens fixing
   hypothetical risk. The prompt forces a "concrete-failure-story" filter:
   if codex cannot name a realistic scenario with realistic inputs at a
   realistic call site, the finding is dropped or downgraded to priority 0/1
   with explicit "I cannot construct the failure" framing in the body.

Together these two pull codex toward "exhaustive on real bugs, silent on
theoretical ones" — the shape a senior human reviewer would produce.

**Turn cap change.** `codex_max_turns: 2 → 5`. The new "5" is across the
PR's lifetime (one turn per push), not 5 stacked turns in one webhook —
see §3.3.

### 3.3 One codex turn per webhook (lifetime budget across pushes)

**Today:** a single `pull_request.synchronize` webhook runs codex for up to
2 turns back-to-back inside one webhook handler. Turn 2 has nothing new to
look at — the diff and codebase are unchanged from turn 1 — so it
predictably re-emits a near-identical review and trips the consensus subset
rule. The 2-turn loop wastes a paid codex invocation per push.

**New:** one codex turn per webhook. The "5 turns" budget spans the PR's
lifetime: turn 1 fires on `pull_request.opened`; turns 2..5 fire on each
subsequent `pull_request.synchronize` (i.e., each push by Claude after
seeing the prior review). After turn 5, no further codex review fires on
this PR — the human takes over. This matches the operator's existing manual
fallback behavior.

The per-stage loop in `_run_stage` (the codex stage only — opencode is
unchanged) becomes a single-iteration call followed by a state write.
`turn_number` is computed as `1 + count(prior codex turns for this pr_url)`.
The 5-cap is enforced by checking that count before spawning the
subprocess; if the cap is reached, emit a single structured warning and
return without posting a review.

**Why not keep the per-webhook loop and just lower it to 1?** Same shape
either way at the call site. We're explicit about the model change so a
future reader understands why turn 2's prompt depends on prior pushes,
not prior in-process turns.

### 3.4 Cross-push memory: findings transcript + codebase learnings

Two distinct kinds of state are persisted per `(pr_url, head_sha,
turn_number)`:

**(i) Findings transcript** — the JSON output of the codex review (the
existing `findings` array from `review-schema.json`) plus, per finding, any
GitHub reply comments authored by the PR author (Claude) that GitHub
threads against that finding's review thread. Lets turn N+1 see exactly
what was flagged before and how the author responded.

**(ii) Codebase learnings** — a free-form structured block codex emits
*about the codebase* (not the diff) on each turn. Examples: "the Review
context exposes `IReviewTurnRegistry` as the only way Gateway reaches
`pr_review_turns` — direct model imports across that boundary are
violations" or "the test conftest at `tests/conftest.py:42` requires every
new model module to be imported there for `Base.metadata.create_all`." A
turn 1 codex pass on a fresh worktree generates a meaningful page of these;
turn N+1 reads them and skips re-discovering the same facts.

**Schema (`.github/codex/review-schema.json`) — additive change:** add an
optional top-level `learnings` field:

```json
"learnings": {
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "topic": { "type": "string", "maxLength": 80 },
      "note":  { "type": "string", "minLength": 1 }
    },
    "required": ["topic", "note"],
    "additionalProperties": false
  }
}
```

`topic` is a short stable handle so the next turn's prompt can dedupe
("DDD: Review context boundary" appearing twice gets deduped to one).

**Storage:** extend the `pr_review_turns` row, **do not** add a new table.
The existing row is keyed exactly the way we want
(`pr_url, head_sha, stage, turn_number`) and the `Review` context already
owns it. Two new nullable columns:

- `findings_json JSONB NULL` — the full normalized findings array.
- `learnings_json JSONB NULL` — the learnings array.

Reply comments are *not* persisted by us — we re-fetch them from GitHub
each turn. They live there authoritatively; mirroring them into our DB
adds a sync problem with no benefit.

The `IReviewTurnRegistry` protocol gains two methods:

- `record_findings_and_learnings(*, pr_url, head_sha, stage, turn_number,
  findings_json, learnings_json) -> None` — called from `complete_turn`'s
  call site, after a successful review.
- `prior_findings_and_learnings(*, pr_url) -> PriorContext` — returns a
  PR-scoped (NOT SHA-scoped) aggregate: the union of all prior turns'
  findings + learnings for this `pr_url`, oldest first. PR-scoped because
  a fix-up commit changes `head_sha` but the prior findings/learnings are
  still the relevant memory.

**Prompt assembly for turn N (N ≥ 2):** before the existing prompt body,
prepend a new section:

```
## Prior review history (turns 1..N-1)

You have reviewed earlier commits of this PR. Here is what you found and
how the author responded.

### Learnings about this codebase from prior turns
- {topic}: {note}
- ...

### Prior findings and author responses
- Turn 1, {file}:{line} — {title} (priority {p})
  Body: {body}
  Author response: {github thread reply or "(no response)"}
- ...

If a prior finding is now resolved by the new diff, do not re-flag it. If
a prior finding is not addressed and you still believe it, re-state it
this turn — the cap counts turns, not findings.
```

The PR body (the §3.1 template Claude filled) is also added to the prompt
verbatim under a `## What this PR is doing` heading, regardless of turn
number. This solves the "codex reviews blind" problem from §1 even on
turn 1.

## 4. Schema migration

One additive Alembic revision in `src/alembic/versions/`:

- Add `pr_review_turns.findings_json JSONB NULL`.
- Add `pr_review_turns.learnings_json JSONB NULL`.

Both nullable so historical rows (which never had this data) remain valid.
Down-migration drops both columns.

`tests/conftest.py` — no change; the model module is already imported.

## 5. File-by-file delta

| File | Change |
| --- | --- |
| `.github/pull_request_template.md` | New — sections per §3.1. |
| `plugins/cloglog/skills/github-bot/SKILL.md` (or wherever `gh pr create` is documented for agents) | Add one paragraph: "before `gh pr create`, fill every section of the template; the codex reviewer reads the body verbatim." |
| `.github/codex/prompts/review.md` | Append the "Be exhaustive" section per §3.2. Add the "Prior review history" preamble per §3.4 (rendered by the backend; the prompt file documents the shape). |
| `.github/codex/review-schema.json` | Add optional `learnings` array field per §3.4. |
| `src/shared/config.py` | `codex_max_turns: 2 → 5`. |
| `src/review/models.py` | Add `findings_json`, `learnings_json` columns. |
| `src/review/interfaces.py` | Add `record_findings_and_learnings` and `prior_findings_and_learnings` methods + a `PriorContext` dataclass. |
| `src/review/repository.py` | Implement the two new methods. |
| `src/review/services.py` | Wire the two new methods into the registry adapter. |
| `src/gateway/review_engine.py` | (a) Drop the per-webhook codex inner loop; codex stage runs exactly once per webhook. (b) Cap check before subprocess spawn: refuse if `prior_codex_turn_count(pr_url) >= 5`. (c) Inject PR body + prior-review-history preamble into the codex prompt. (d) After a successful review, call `record_findings_and_learnings`. (e) After a successful review, fetch GitHub reply comments for each prior finding's review thread (one `gh api repos/X/pulls/N/reviews/M/comments` per turn) for use in the next turn's preamble assembly. |
| `src/alembic/versions/<new>_pr_review_turns_findings_learnings.py` | Additive migration. |
| `tests/gateway/test_review_engine_*.py` (new + extended) | Tests below. |

## 6. Diagnostic plan (must run before §3.2 fix lands)

The "exhaustive" fix depends on knowing which of (a)–(d) in §3.2 is the
dominant cause. The diagnostic is one PR's worth of instrumentation:

1. Pick a recent PR with a known small codex review (2–3 findings) on a
   non-trivial diff.
2. Add `print` / structured log lines around the codex subprocess
   invocation in `review_engine.py`: full argv, prompt token count
   (approximated by `len(prompt) // 4`), raw stdout, raw stderr, exit
   code, elapsed seconds.
3. Re-run `make test-review-engine-codex` (or the equivalent integration
   test that fires the webhook handler with a recorded fixture) against
   that PR's fixtures.
4. Inspect the captured stdout: did the JSON `findings` array end mid-item
   (truncation)? Was it short but well-formed (self-rationing)? Did the
   subprocess exit before printing more (CLI cap)? Was the review-loop
   short-circuiting on the consensus rule (predicate fired)?
5. Pick the fix(es) accordingly:
   - Truncation → raise the CLI's output cap flag (look in
     `--max-output-tokens` or analog) **and** add the "Be exhaustive"
     prompt language.
   - Self-rationing → "Be exhaustive" prompt language alone.
   - CLI cap → CLI flag.
   - Predicate firing → tighten the consensus check (e.g., require a
     minimum `turn_number ≥ 3` before subset-of-prior can short-circuit).
     But note: with §3.3, the per-webhook loop becomes single-iteration,
     so the consensus predicate's role shifts to *cross-push* short-circuit
     only — which is exactly what we want.

The diagnostic output goes into the PR description; the chosen fix is the
implementation commit.

## 7. Tests

Real-DB integration tests in `tests/gateway/`:

- `test_codex_runs_once_per_webhook`: webhook fired with 2 codex turns
  expected by old code path → assert exactly one `pr_review_turns` row
  was created, exactly one GitHub review POST.
- `test_codex_turn_cap_lifetime_5`: simulate 6 successive
  `pull_request.synchronize` webhooks on the same PR with different
  `head_sha` → assert turns 1..5 produce a row, turn 6 does not (cap
  enforced) and emits the structured warning.
- `test_prior_findings_in_prompt`: webhook 2 fires after webhook 1
  produced 3 findings → assert the codex prompt for webhook 2 contains
  all 3 prior findings with their author-response slots.
- `test_pr_body_in_prompt`: webhook fires with a PR body containing the
  template → assert the codex prompt contains the body under
  `## What this PR is doing`.
- `test_learnings_round_trip`: codex emits a `learnings` array → assert
  it is persisted in `pr_review_turns.learnings_json` and surfaces in
  the next turn's prompt.
- `test_learnings_dedup_by_topic`: turns 1 and 2 emit the same
  `topic: "DDD: Review context boundary"` → next-turn prompt shows it
  once.

Pin tests:
- `test_pr_review_turns_jsonb_columns_nullable` — historical rows
  without the new columns must still load.
- `test_codex_review_schema_learnings_optional` — schema change is
  additive; PRs whose codex run pre-dates the schema bump must still
  parse.

## 8. Failure modes & explicit non-goals

- **PR template skipped by an agent.** Codex degrades gracefully: prompt
  shows whatever PR body exists. No retry, no rejection. If this becomes
  endemic, revisit with hard enforcement.
- **Learnings drift from reality.** If a prior turn learned "X is true"
  and X stops being true in a later commit, codex sees both the (now
  stale) learning and the new code. The prompt's "do not re-flag resolved
  findings" guidance also covers stale learnings — codex is expected to
  notice. We do **not** try to invalidate learnings server-side; that's a
  bigger problem than this task solves.
- **Reply-comment fetch is best-effort.** If `gh api ... /comments` fails
  for the prior turn's reviews, we render `(unable to fetch responses)`
  in the preamble and continue. We do not block the review.
- **Cross-PR memory is not in scope.** Learnings persisted on PR #100 do
  NOT seep into PR #101's review prompt. Each PR's memory is isolated.
  Cross-PR codebase learnings are a credible follow-up but not this task.
- **Hot-process codex is not in scope.** All persistence is via DB rows
  + prompt replay. No daemon, no session resumption, no codex CLI
  `--continue`. Operator's "soft" goal explicitly accepted this trade.

## 9. Rollout

The four deliverables are independent and can land as four separate
commits on the same PR:

1. PR template + skill instruction (no code, no risk).
2. Schema migration + `pr_review_turns` columns + new repository methods
   (additive, no behavior change yet).
3. Diagnostic + early-stop fix + turn-cap change + per-webhook
   single-iteration change. The behavioral pivot.
4. Cross-push memory wiring: prompt assembly reads prior
   findings/learnings, codex output writes them.

Each commit keeps `make quality` green. The PR opens after all four land
locally.
