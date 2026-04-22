# Reviewers have a single design doc that pins every semantic of the two-stage iterative PR review pipeline T-248 will implement — opencode (gemma4:e4b) for up to 5 turns, then codex for up to 2 turns, short-circuiting on consensus.

*2026-04-22T17:09:36Z by Showboat 0.6.1*
<!-- showboat-id: 28b557c7-a409-405d-9929-04b8270785a7 -->

### The 8 questions and their answers (one-liners)

1. **Per-reviewer loop semantics / consensus** → option (c): explicit `status: no_further_concerns` flag OR zero-new-findings (tuple key `(file, line, title_lower)`). Worked example in §1.2.
2. **Sequencing** → strictly serial, handled by a single `WebhookConsumer` that `await`s stage A then stage B (no new event type). §2.
3. **Turn accounting** → new **`Review` bounded context** at `src/review/` owning the `pr_review_turns` table — Gateway cannot own tables per `docs/ddd-context-map.md`, so Gateway consumes `IReviewTurnRegistry` via Open Host Service. Table keyed `(pr_url, head_sha, stage, turn_number)`; idempotency via `INSERT ... ON CONFLICT DO NOTHING`; new SHA resets BOTH loops symmetrically. §3.
4. **Identity** → two GitHub App bots (`cloglog-opencode-reviewer[bot]`, `cloglog-codex-reviewer[bot]`); PEMs at `~/.agent-vm/credentials/*.pem` (same precedent as existing codex bot — `~/.cloglog/credentials` is for the backend API key only, NOT reviewer tokens); author-skip fix MUST change `handles()` to `event.sender in _REVIEWER_BOTS` (today's check is `== _CODEX_BOT` and `_BOT_USERNAMES` is not consulted); visible turn header `**opencode (gemma4:e4b) — turn 3/5**`. §4.
5. **Timeouts + startup gate** → opencode 180 s / turn, codex 300 s / turn; 5xx and 409 NOT retried; transient `ECONNRESET`/`ETIMEDOUT` get one ≥ 2 s backoff; dead opencode never blocks codex at runtime (§5.3). New at boot: `app.py` lifespan now probes BOTH binaries (`is_review_agent_available()` extended with `is_opencode_available()`); registration falls to codex-only / opencode-only / disabled per the §5.4 matrix so a host missing one binary does not spam skip-comments. §5.
6. **Contention / queuing** → one review at a time via existing `asyncio.Lock`; implicit FIFO, no dropping/deferring. Rate limit and per-PR cap counted per **session**, not per turn. §6.
7. **Structured output** → additive top-level `status` on `review-schema.json` PLUS matching `ReviewResult.status` field PLUS `_parse_output` preserves it through Codex-schema normalization (today `_parse_output` rewrites data to `{verdict, summary, findings}` only, silently dropping any `status` — without all three changes the explicit-consensus branch is a dead branch). §7.
8. **Observability** → `review_turn_start` / `review_turn_end` / `review_stage_end` / `review_session_end` structured log lines; metric names reserved; task-card badge extended to `opencode 2/5` / `codex 1/2`. §8.

### Proof the artifact exists and is complete

```bash
test -f docs/design/two-stage-pr-review.md && echo "spec_file_exists=true"
```

```output
spec_file_exists=true
```

```bash
for n in 1 2 3 4 5 6 7 8; do
     c=$(grep -c "^## ${n}\. " docs/design/two-stage-pr-review.md || true)
     echo "question_${n}_header_count=${c}"
   done
```

```output
question_1_header_count=1
question_2_header_count=1
question_3_header_count=1
question_4_header_count=1
question_5_header_count=1
question_6_header_count=1
question_7_header_count=1
question_8_header_count=1
```

```bash
grep -qE "^## What changes in T-248" docs/design/two-stage-pr-review.md && echo "t248_delta_section=present"
```

```output
t248_delta_section=present
```

```bash
for f in src/gateway/review_engine.py src/gateway/app.py src/shared/config.py src/gateway/github_token.py .github/codex/prompts/review.md .github/codex/review-schema.json src/alembic/versions/ src/review/ docs/ddd-context-map.md; do
     r=$(grep -c "\`${f}\`" docs/design/two-stage-pr-review.md || true)
     echo "names_${f}=$( [ "$r" -gt 0 ] && echo yes || echo no )"
   done
```

```output
names_src/gateway/review_engine.py=yes
names_src/gateway/app.py=yes
names_src/shared/config.py=yes
names_src/gateway/github_token.py=yes
names_.github/codex/prompts/review.md=yes
names_.github/codex/review-schema.json=yes
names_src/alembic/versions/=yes
names_src/review/=yes
names_docs/ddd-context-map.md=yes
```

### First section of the design doc (for reviewer skim)

```bash
awk "/^## 1\\. Per-reviewer loop semantics/{found=1} found && /^## 2\\. Sequencing between stages/{exit} found" docs/design/two-stage-pr-review.md | head -40
```

````output
## 1. Per-reviewer loop semantics

### Per-turn shape (both stages)

A single turn is:

1. Fetch the filtered diff for the PR (re-fetched every turn — a concurrent push may have landed).
2. Read the running comment history: all reviews + inline comments posted by **either** reviewer bot on this PR, across all turns. Limited to the current commit SHA.
3. Invoke the reviewer (subprocess for codex; subprocess for opencode). Prompt contains: diff + CLAUDE.md + comment history so far + the turn label (`turn N/MAX`).
4. Parse the reviewer's structured JSON output into `ReviewResult` (existing type).
5. Post one GitHub review (event `COMMENT`) containing all inline findings for this turn, tagged with the turn label in the body header.
6. Persist a `pr_review_turns` row (see §3) with `finding_count`, `elapsed_seconds`, `consensus_reached`.
7. Evaluate consensus (§1.1). If reached, exit the loop; otherwise, continue until the per-stage cap.

### 1.1 Consensus definition — option (c), **both**

**Consensus is reached on turn N when at least one of these is true:**

**(a) Explicit flag.** The reviewer's structured output includes `"status": "no_further_concerns"` (a new optional field on the review schema; absent = not-yet-consensus). This is the reviewer *saying* it is done.

**(b) Empty-diff.** The reviewer's `findings` array for turn N contains zero items whose `(file, line, title_lower)` tuple is not already in the union of all prior turns' findings on this `(pr_url, head_sha)`. This is the reviewer *behaving* as if done.

Either trigger ends the loop. **Both** predicates are checked because each has a distinct failure mode alone:

- (a) alone is brittle: a local model may be reluctant to self-assess "done" and keep surfacing minor nitpicks past saturation.
- (b) alone is brittle: minor re-phrasing of the same finding can produce text jitter across turns and falsely look "new."

The tuple key uses `title.lower().strip()` (not `body`) because titles are stable (capped at 80 chars by the schema) and bodies tend to jitter. The `(file, line)` part pins the location so that "the same problem but surfaced at a different line" counts as new.

### 1.2 Worked example — consensus on turn 3

```
Turn 1: opencode emits 4 findings.
  (src/a.py, 42, "Missing None guard")
  (src/a.py, 47, "Dead import")
  (src/b.py, 12, "TODO left in code")
  (src/c.py, 99, "Possible race")

Turn 2: opencode emits 2 findings.
  (src/a.py, 42, "Missing none guard")   ← duplicate, title case-folded
````
