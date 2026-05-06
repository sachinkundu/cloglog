# Tuning the cloglog codex reviewer — lessons from the Cloudflare AI code review post

**Source:** https://blog.cloudflare.com/ai-code-review/
**Date:** 2026-05-06
**Task:** T-479 (explore-only).
**Scope:** This is a research note. Each recommendation defends itself
against the operator's self-defense rule — *"if dropped, what ships
broken?"* Recommendations whose only answer is "nothing visible" or
"would be cleaner" are noted in §7 (gaps, not filed) rather than filed
as follow-ups.

## 1. Cloudflare's pipeline in cloglog vocabulary

Cloudflare runs an OpenCode-based coordinator-and-specialists pipeline
on every GitLab MR:

1. A **coordinator** session (Opus 4.7 / GPT-5.4 tier) reads the diff,
   classifies it into a risk tier (trivial ≤10 LOC / lite ≤100 / full
   >100 or security-touching), then calls a `spawn_reviewers` tool that
   launches up to **seven specialist sessions in parallel** —
   security, performance, code quality, documentation, release,
   internal RFC compliance, AGENTS.md freshness.
2. Specialists each get the **patch files for their domain only** (not
   the full diff embedded in the prompt) and a **shared
   `REVIEWER_SHARED.md`** plus their agent-specific markdown. They
   return findings as structured XML with severity
   (`critical`/`warning`/`suggestion`).
3. The coordinator deduplicates, re-categorises severity, drops
   "reasonableness-failed" findings, and posts one consolidated review
   plus inline DiffNotes.
4. Re-reviews on subsequent pushes get **the previous review body and
   the resolution status of each prior inline comment** as input — the
   coordinator decides what to re-state vs drop.

Mapping into cloglog terms:

| Cloudflare component | cloglog analogue today |
|---|---|
| Coordinator session | none — we have no orchestrator above the reviewers |
| OpenCode specialist (security/perf/etc.) | `OpencodeReviewer` (single advisory critic, not domain-split) |
| Codex specialist (RFC compliance) | `CodexReviewer` (does *all* dimensions in one pass) |
| Risk-tier dispatcher | `compute_review_timeout` (timeout-only, not coverage-tier) |
| `spawn_reviewers` parallel fan-out | `ReviewLoop` × 2 stages, **strictly serial** (`docs/design/two-stage-pr-review.md` §2.1) |
| Re-review with prior-comment resolution status | T-367 cross-push memory + `PriorContext` injection |
| `auto_merge_gate.py` consensus | `_reached_consensus` — explicit flag OR empty-diff predicate |

Their median review takes 3:39 across 131k runs at $0.98/review. Our
review takes ~5–10 min per codex session at unknown cost (we don't
meter), and we run at most ~30 PRs/week. Different scale entirely —
their cost optimisations (cache hit rate, parallel fan-out for latency)
are not load-bearing for us.

## 2. Multi-agent / sub-agent pattern

**Cloudflare's shape.** A lead "coordinator" agent (top-tier model)
**dispatches up to 7 parallel specialists** (standard-tier or
lightweight-tier models, scoped per domain). The coordinator sees what
the specialists return; specialists do not see each other's output.
Dispatch is **selective by risk tier** — trivial diffs spawn 1
generalist, lite spawns 4, full spawns all 7+. Security-sensitive paths
(`auth/`, `crypto/`) **always** trigger the full set regardless of
size.

**Why it works for them.** Three things they get from the split that a
single-prompt reviewer struggles with:

1. **Per-specialist "what NOT to report" lists.** Their security
   reviewer's prompt explicitly excludes "theoretical risks requiring
   unlikely preconditions," "defense-in-depth when primary defenses are
   adequate," and "issues in unchanged code." A generalist prompt that
   covers seven dimensions can't carry seven independent
   anti-noise-lists without bloating beyond useful attention.
2. **Per-specialist model tier.** Documentation review uses a
   lightweight model (Kimi K2.5); security uses a standard tier. We
   pay strong models only where they earn their cost.
3. **Coordinator-side post-processing.** Dedup across specialists,
   severity recalibration, "reasonableness filtering." The
   coordinator's job is not reviewing — it's curation.

**Does cloglog need this?** No, with caveats.

Today's two-stage pipeline (`opencode → codex`) **is not** a
coordinator/specialist pattern. Both reviewers cover the same dimension
list (everything); they're independent critics of the same surface,
serial because of GPU contention, not because of task split. The
"specialisation" Cloudflare gets from 7 prompt files we approximate
with **one big codex prompt** that lists all the things to look for.

A Cloudflare-style multi-agent split would only earn its weight on
cloglog if **at least one** of these were true:

- We were paying per-PR cost we wanted to cut by routing simple
  dimensions to a cheaper model. *We aren't — we pay one tier
  (Claude-API Sonnet/Opus) regardless.*
- Different reviewers needed mutually incompatible "what NOT to
  report" lists. *They might — see §4 — but the workaround is one
  longer codex prompt, not seven sessions.*
- We had a noise problem traceable to dimension-cross-talk (e.g.
  "security model emits style nits because we asked it to think about
  style too"). *Not observed today. PR #330 missed sites; it didn't
  surface noise.*

**Concrete recommendation: keep the current shape.**

- **Reject:** "Restructure into coordinator + 5 specialists." Cost is a
  full pipeline rewrite + 4 new GitHub App identities + 4 new prompt
  files + a coordinator session that reads each specialist's output;
  payoff is unclear because we have no observed noise problem driven by
  generalist scope. **Self-defense:** if we drop this idea, what ships
  broken? Nothing — the pipeline already produces low-noise reviews on
  most PRs (PR #329 noise was a different failure mode: codex
  *exhaustion*, not dimension-cross-talk).
- **Defer (note, do not file):** if a future PR shows codex emitting
  high-volume vague suggestions across mixed dimensions (the
  Cloudflare "firehose of speculative theoretical warnings" failure
  mode), revisit. Today the failure mode is the *opposite* — codex
  misses real findings (PR #330 row #31).

The closer architectural lesson is: their **coordinator** does
post-processing (dedup, severity recalibration). We have no
post-processing layer between codex's structured output and the GitHub
review POST. That's a separate, smaller question — addressed in §3 and
§4.

## 3. Tunables we already have but might be using wrong

### 3.1 `REVIEW_TIMEOUT_BASE_SECONDS = 300`, `REVIEW_TIMEOUT_PER_LINE_SECONDS = 0.5`, `REVIEW_TIMEOUT_CAP_SECONDS = 1800`

Cloudflare's per-task timeout is **5 min standard, 10 min for code
quality**, with a **25-minute overall hard cap** and a "retry budget:
2 min minimum — we don't bother retrying if there isn't enough time
left." They explicitly call out that **"if a session has been running
for 60 seconds with no output at all, it is killed early."**

PR #330 was 111 changed lines and codex took 355s — under our
`300 + 0.5×111 = 355.5s` budget by margin of <1s. The current
linear-scale curve **is on the edge of false-positive-timeouts on
small docs PRs.** Cloudflare's flat-5-min-per-task is more
conservative on the small end and matches our observation.

**Recommendation:** Raise `REVIEW_TIMEOUT_BASE_SECONDS` from 300 → 420
(7 min). Keep per-line and cap unchanged. Justification: PR #330
demonstrates the floor is already too tight; widening base by 40% buys
headroom on the size class where codex spends most of its time
(reading neighbour files via filesystem access, not just diff parse).

- **Adopt** with self-defense: if we don't ship this, PRs near the
  100-line / 5-min boundary keep timing out and forcing human merge.
  PR #330 was a real instance, not hypothetical.
- **Follow-up title:** "Raise `REVIEW_TIMEOUT_BASE_SECONDS` to 420s."

### 3.2 Per-turn caps and consensus stop rules — already in place

**Correction (codex round 1).** The current settings are
`codex_max_turns = 1` (set in `src/shared/config.py:50-58`, deliberate
T-367 change documented in `docs/work-logs/2026-05-02-wave-t367-codex-memory-work-log.md`)
and `MAX_REVIEWS_PER_PR = 5`. The `_reached_consensus` predicate at
`src/gateway/review_loop.py:344-364` already implements predicate (c)
"no new findings vs. all prior turns" — including the case-normalized
subset-of-prior check pinned by `tests/gateway/test_review_loop.py:380-396`.

So a recommendation to "add subset-of-prior consensus" would be a
no-op. PR #329's 5/5 exhaustion did NOT happen because the predicate
was missing — each round's findings were genuinely new (codex found
different real issues each pass on the spec). The exhaustion is a
content problem, not a stop-rule problem.

Cloudflare cites a re-review average of **2.7 reviews per MR**
(initial + re-reviews on push) and doesn't bound turns within a single
review — their coordinator's single-pass design doesn't iterate. Their
data point: **0.6% of MRs hit a "break glass" override** (288 / 48,095).
Our break-glass rate on the comparable PRs we've shipped this week is
higher — probably 5–15% — but the diagnosis is **not** missing stop
rules; the predicates are in place.

**Recommendation:** Do NOT change the per-PR cap or consensus rules
today. The genuine exhaustion driver is *findings churn* (codex
finding new real issues round after round on long specs), and the
intervention space for that is upstream prompt or input-shape
changes, not stop-rule plumbing. Cloudflare's 0.6% break-glass rate
comes from a different mechanism — their
coordinator runs once, then the human pushes a fix, and the next
review is a *fresh* review on the new SHA, not turn N+1 of the same
review. Our exhaustion comes from codex disagreeing with itself across
turns on the same SHA (PR #329 spec-rejection loop). Adding more turns
gives codex more rope; what we want is a **stop predicate** that
recognises a low-information loop earlier.

- **Reject** "raise `codex_max_turns`."
- **Defer (note):** "Add a no-information-gain consensus predicate
  (predicate (d): if turn N's findings are a *subset* of prior
  findings, treat as consensus)." This is closer to what their
  coordinator's "reasonableness filtering" achieves. Cost is one
  short helper in `_reached_consensus`. Self-defense: if we don't
  ship this, PR #329-class spec-loop exhaustion keeps happening.
  Worth filing as a follow-up.
- **Follow-up title:** "Treat finding-set ⊆ prior-set as consensus
  (predicate d)."

### 3.3 Prompt-shared file (`REVIEWER_SHARED.md`)

Cloudflare splits the agent prompt into **agent-specific markdown +
shared `REVIEWER_SHARED.md`**. Sub-reviewers read this file rather than
having the full MR context duplicated in each prompt — load-bearing
for their **85.7% prompt-cache hit rate.**

We don't run multi-agent so this concrete split doesn't apply. But the
*shape* of the lesson — keep the bulky stable prefix at the front of
the prompt for cache reuse — does apply, **iff** we use prompt
caching. We don't today (codex CLI invocation, no cache config).

- **Defer (note, do not file):** Prompt caching for codex review.
  Cloudflare's "five-figure savings" estimate is at 130k reviews. We
  do ~1500 reviews/year. The infrastructure cost (porting from codex
  CLI invocation to a caching-aware wrapper) outweighs ~$0–$50/year
  of API spend.

### 3.4 Prompt scope on the live runtime prompt — already trimmed

**Correction (codex round 1).** The runtime prompt the live review
engine loads is `.github/codex/prompts/review.md` (per
`src/gateway/review_engine.py:413-418`), NOT
`plugins/cloglog/templates/codex-review-prompt.md` — that template is
read only at project initialization to generate the project-specific
prompt (`plugins/cloglog/skills/init/SKILL.md:894-900`). The current
`.github/codex/prompts/review.md:1-120` already contains no
"Demo expectations" block — the dimension-cross-talk this section
originally proposed eliminating is already not a problem in the live
prompt.

PR #330 row #31 (codex missed sites grep finds) is therefore not
explained by demo-audit cross-talk. The likelier cause is the
inherent limitation of LLM review on docs-sweep tasks where the
deterministic grep is the right tool — covered by the systematic
post-codex-grep pattern T-435 itself adopted ("How this sweep was
conducted (after codex review)").

- **Drop.** No follow-up to file. If the operator's intent is to
  also ensure the *plugin template* (used to seed future repos)
  stays free of demo-audit content, that is a separate plugin-side
  concern, not a tuning of the live cloglog reviewer. Note the
  distinction and move on.

## 4. Prompt-engineering lessons

Cloudflare's most-quoted sentence in the post:

> "Telling an LLM what **not** to do is where the actual prompt
> engineering value resides. Without these boundaries, you get a
> firehose of speculative theoretical warnings."

Our codex prompt has a "What NOT to report" section (lines 45–52) — we
already follow this principle. Concrete items they list that we don't:

- **"Theoretical risks requiring unlikely preconditions."** We don't
  call this out. Codex on PR #322 emitted a finding about a race
  requiring concurrent webhook-delivery + DB failover — a theoretical
  risk we don't operate at scale to hit.
- **"Defense-in-depth suggestions when primary defenses are adequate."**
  Same gap. Codex regularly suggests "consider also validating X" on
  inputs already validated upstream.
- **"`Consider using library X` style suggestions."** We have "no
  suggestions that don't fix a real problem" (line 50) but not the
  specific library-suggestion pattern.

**Recommendation:** Extend the "What NOT to report" section of the
**live runtime prompt at `.github/codex/prompts/review.md`** (per
`src/gateway/review_engine.py:413-418`) with these three items,
copied close to verbatim from Cloudflare's security-reviewer prompt
(with attribution). This is a ~10-line prompt edit; the win is fewer
noise findings on PRs that already pass.

The current `.github/codex/prompts/review.md:65-72` "What NOT to
report" section is the correct edit target. The plugin template at
`plugins/cloglog/templates/codex-review-prompt.md` is generic seed
material for future repos — touching it would NOT change cloglog's
own reviewer behaviour; that is a separate decision (port the same
wording forward so future projects start with the tuned shape too).

- **Adopt — but target `.github/codex/prompts/review.md`, not the
  plugin template.** Self-defense: if we don't ship this, codex
  keeps emitting low-information theoretical-risk findings that the
  operator manually ignores. The cost of NOT shipping is recurring
  "this finding is correct in theory but irrelevant" human-merge
  friction.
- **Follow-up title:** "Add Cloudflare-style anti-noise items to
  `.github/codex/prompts/review.md` 'What NOT to report' list."
  Optional second follow-up, dependent on operator intent: port the
  same wording into `plugins/cloglog/templates/codex-review-prompt.md`
  so newly-`init`'d projects inherit the tuning.

### Where Cloudflare doesn't help us

Their **prompt injection prevention** (stripping `</mr_body>`-style
boundary tags from MR descriptions) is a real concern at their scale
(48k MRs/month, untrusted contributors). cloglog runs on PRs authored
by our own bot or the operator. Untrusted-content injection isn't a
concern today.

- **Reject.** Self-defense: nothing ships broken. Single-operator
  threat model.

## 5. Failure modes — mapping cloglog incidents to Cloudflare's design

| cloglog observation | Cloudflare addresses it? | How |
|---|---|---|
| **PR #330: codex timeout on 111-line docs PR (355s)** | Partial | Their per-task timeout is 5 min flat. Our linear-scale curve has a too-tight floor at this size. Already covered in §3.1. |
| **PR #329: 5/5 session exhaustion on T-432 spec** | No | Their coordinator is single-pass — there's no concept of "5 sessions" in their model. The closest analogue is the 0.6% break-glass override. They don't claim a fix; they accept that some MRs need human override. The sub-set consensus predicate proposed in §3.2 is a cloglog-only mitigation. |
| **PR #330 row #31: codex missed sites grep finds** | Partial | Their architectural blind-spots paragraph: *"the reviewers see the diff and surrounding code, but they don't have the full context of why a system was designed a certain way."* Their fix is the coordinator + multiple specialists — *not* a tunable. The cloglog-side fix is the prompt-broadness reduction in §3.4. |
| **Codex emits theoretical-risk findings** | Yes | Anti-noise list in §4. Their solution is exactly what we should adopt. |

The PR #330 row #31 case (deterministic grep finds sites codex misses)
deserves a note Cloudflare doesn't address: **a deterministic
pre-pass.** If we know `auto_merge_gate.py` runs `grep` and `ruff` and
our codex still misses sites those tools find, the right answer is
running grep/ruff *first* and feeding their output to codex as
"hints," not asking codex to be better at being grep. This is outside
Cloudflare's lessons (they don't show their pre-pass tooling).

- **Defer (note, do not file).** Filing this is a real implementation
  task with unclear scope (which greps? which lint outputs? injected
  how?). Worth re-examining if §3.4 (drop demo-audit block) doesn't
  resolve the miss-rate. Self-defense: if we don't file this *yet*,
  what ships broken? Nothing additional — §3.4 is the cheaper fix
  for the same symptom; try it first.

## 6. Verdict — follow-up tasks to file

Three adoptions, defended by the operator's self-defense rule. Each
is a ≤30-line change and the cost of not shipping is concrete and
recurring.

| # | Title | Cost | What ships broken if dropped |
|---|---|---|---|
| 1 | Raise `REVIEW_TIMEOUT_BASE_SECONDS` to 420s | 1-line constant | PRs near the 100-line / 5-min boundary keep timing out (PR #330 instance) |
| 2 | ~~Treat finding-set ⊆ prior-set as consensus~~ — **DROPPED, already shipped.** `_reached_consensus` (`src/gateway/review_loop.py:344-364`) already implements this; pinned by `tests/gateway/test_review_loop.py:380-396`. PR #329's 5/5 exhaustion was findings-churn, not a missing predicate. |  |  |
| 3 | ~~Drop "Demo expectations" block~~ — **DROPPED, already absent.** The live runtime prompt `.github/codex/prompts/review.md` has no such block; only the plugin template would have the issue, and editing it does NOT retune the live reviewer. |  |  |
| 4 | Add Cloudflare-style anti-noise items to "What NOT to report" in `.github/codex/prompts/review.md` (live runtime prompt — NOT the plugin template) | ~10 lines added | Codex keeps emitting theoretical-risk findings that the operator manually ignores in auto-merge overrides |

## 7. Gaps noted but not filed (self-defense rule failed)

- Multi-agent coordinator/specialist split (§2). Big rewrite, no
  observed noise problem driven by generalist scope.
- Prompt caching for codex (§3.3). API spend too low to justify
  porting away from the codex CLI invocation.
- Per-specialist model tier (lightweight model for doc-only PRs)
  (§3.3). We pay one tier per review; would only matter at
  ~10x current PR volume.
- Pre-pass deterministic tooling feeding codex (§5). Cheaper fix
  (§3.4 drop demo block) addresses the same miss-rate symptom; try
  that first.
- Prompt-injection boundary stripping (§4). Single-operator threat
  model.

## 8. What this exploration explicitly did NOT do

- Implement any of the four follow-ups above. Each is its own task.
- Compare against GitHub Copilot, CodeRabbit, or other commercial
  review systems (out of scope per task description).
- Re-examine `docs/design/codex-exhaustive-review.md` for prompt-
  design alternatives Cloudflare doesn't cover. The codex-prompt
  edits in adoption #3 and #4 are the only prompt changes this
  exploration recommends.
