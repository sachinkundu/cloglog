# Two-stage iterative PR review pipeline — design spec

**Status:** Accepted (pending merge)
**Scope:** Pins the exact semantics of the PR review pipeline that T-248 will implement.
**Blocks:** T-248 (impl).
**Context:** T-261 on the board. F-47 (PR Review Webhook Server) extends F-36 (single-pass codex reviewer) into a **two-stage iterative** pipeline.

## Target pipeline (one sentence)

On `pull_request.opened` / `pull_request.synchronize`, run **opencode (`gemma4:e4b`, 128K ctx) for up to 5 turns**, then **codex (Claude-API via OpenAI Codex CLI) for up to 2 turns**, short-circuiting either loop the moment that reviewer reaches consensus — then hand the PR back to the human author.

## Why two stages, not one

Opencode (`gemma4:e4b`, local) and codex (cloud) are **independent critics with different training distributions**. Running both catches a strictly larger set of findings than either alone. Opencode is free per inference; running it first and iterating to consensus means by the time the paid codex reviewer runs, it is reviewing a more-polished PR and needs fewer turns — so aggregate Claude-API spend goes *down*, not up, at steady state.

Serial (not parallel) because: (a) codex benefits from seeing the author's responses to opencode's findings — those responses are signal; (b) the local machine has one GPU; two gemma4:e4b loads would contend for VRAM; (c) a strictly-ordered pipeline has a much simpler state machine than two concurrent loops with a barrier.

## Architecture snapshot — what lives where today

The implementation will touch exactly these files:

| File | Today | Change in T-248 |
|------|-------|-----------------|
| `src/gateway/review_engine.py` | `ReviewEngineConsumer` runs a single codex pass per webhook | Refactor into `TwoStageReviewSequencer` that orchestrates two `ReviewLoop` runs (opencode + codex). Extract a `Reviewer` protocol; `CodexReviewer` wraps the current subprocess path; new `OpencodeReviewer` wraps opencode CLI. |
| `src/gateway/app.py` (lifespan) | Registers `ReviewEngineConsumer` | Register the new sequencer in its place. |
| `src/shared/config.py` | `review_agent_cmd`, `review_max_per_hour`, `review_source_root` | Add `opencode_cmd`, `opencode_model`, `opencode_max_turns`, `codex_max_turns`, `opencode_turn_timeout_seconds`. All optional, all default to sane values listed below. |
| `src/gateway/github_token.py` | `get_codex_reviewer_token()` | Add `get_opencode_reviewer_token()`, same pattern. |
| `.github/codex/prompts/review.md`, `review-schema.json` | Prompt + schema for codex | Add `.github/opencode/prompts/review.md` (separate prompt — instructs the local model to emit the same JSON schema). Reuse `review-schema.json` verbatim; do NOT fork it. |
| `src/alembic/versions/` | Existing revisions | Add an additive migration that creates the `pr_review_turns` table (see §3). |
| New: `src/gateway/review_loop.py` | — | Houses `ReviewLoop`, `Reviewer` protocol, consensus check. Small — ~120 LOC. |
| `tests/test_review_engine.py`, new `tests/test_review_loop.py`, `tests/test_opencode_reviewer.py` | — | Real-DB tests for the loop, consensus, idempotency, and opencode adapter. |

`src/gateway/webhook_dispatcher.py`, `src/gateway/webhook_consumers.py`, and the webhook endpoint in `src/gateway/webhook.py` are **not** touched — the sequencer is just a different `WebhookConsumer`.

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
  (src/d.py, 14, "Unhandled exception")  ← NEW

Turn 3: opencode emits 1 finding.
  (src/a.py, 42, "Missing None guard")   ← duplicate (identical tuple)
  [JSON "status": "no_further_concerns"]

Result: consensus reached at turn 3.
  - (a) is true: explicit flag.
  - (b) is also true: the 1 finding is not new.
  - Record `consensus_reached=true`, `turns_used=3`, exit loop before turn 4.
```

### 1.3 Per-stage caps

- opencode: `opencode_max_turns = 5` (default, settable).
- codex: `codex_max_turns = 2` (default, settable).

Caps are **maximums**; consensus can end the loop early. A loop that exhausts its cap without consensus is not a failure — it just ran out of budget. The last turn's findings are posted as-is.

## 2. Sequencing between stages

### 2.1 Strictly serial, handled inline

The sequencer is a single `WebhookConsumer` that `await`s stage A then stage B:

```python
async def _review_pr(self, event: WebhookEvent) -> None:
    if not await self._pre_checks(event):  # bot-author, cap, rate-limit, diff-size
        return
    await self._run_stage(OpencodeReviewer(...), event, max_turns=settings.opencode_max_turns)
    await self._run_stage(CodexReviewer(...), event, max_turns=settings.codex_max_turns)
```

**No new event type.** The handoff is a direct in-process `await`. Introducing a `stage_a_completed` event and wiring a second consumer would add one hop, one dispatcher round-trip, and one place for the pipeline to stall silently — with no benefit, because stage A and stage B share process and filesystem.

### 2.2 Where in the F-47 dispatcher

The sequencer sits in the same registration slot as today's `ReviewEngineConsumer` — in `src/gateway/app.py::lifespan`. It subscribes to `PR_OPENED` and `PR_SYNCHRONIZE` and ignores everything else. `AgentNotifierConsumer` runs independently (it listens to merge/review/ci events, not PR-open).

### 2.3 What if stage A fails?

A **dead stage A** (timeout, crash, empty output across all turns) **must not** block stage B. The sequencer posts a skip-comment from opencode bot (reason: `OPENCODE_FAILED`, reusing the `SkipReason` enum pattern) and falls through to codex. "An opencode that never answered" is operationally equivalent to "no opencode reviewer" — codex should still run.

## 3. Turn accounting and storage

### 3.1 Schema — `pr_review_turns`

New table (not new columns on an existing one) because turns are orthogonal to tasks/PRs/projects and putting them on `tasks` would denormalize badly for PRs that span multiple tasks (rare but legal).

```sql
CREATE TABLE pr_review_turns (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pr_url          TEXT NOT NULL,
    pr_number       INT NOT NULL,
    head_sha        TEXT NOT NULL,
    stage           TEXT NOT NULL,   -- 'opencode' | 'codex'
    turn_number     INT NOT NULL,    -- 1..max_turns_for_stage
    status          TEXT NOT NULL,   -- 'running' | 'completed' | 'timed_out' | 'failed'
    finding_count   INT,             -- populated on completion
    consensus_reached BOOL NOT NULL DEFAULT FALSE,
    elapsed_seconds NUMERIC(10,3),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    UNIQUE (pr_url, head_sha, stage, turn_number)
);
CREATE INDEX ix_pr_review_turns_pr ON pr_review_turns (pr_url, head_sha);
```

A `CHECK (stage IN ('opencode', 'codex'))` and `CHECK (status IN (...))` are added in-migration as well. Alembic migration is **additive only** per the project rule in `CLAUDE.md` — no data backfill, no destructive cleanup.

### 3.2 Idempotency against webhook re-fires

The `UNIQUE (pr_url, head_sha, stage, turn_number)` constraint is the primary guard. The sequencer uses `INSERT ... ON CONFLICT DO NOTHING` to claim a turn slot before running, and if the insert reports zero rows written, **another handler is already running this turn — exit immediately, do not double-post.** This covers:

- GitHub re-delivering the same webhook.
- `webhook_dispatcher` delivery-id dedup failing open (e.g., in-memory set eviction).
- Manual replays from the backend's webhook replay console (future).

`head_sha` is taken from `event.raw["pull_request"]["head"]["sha"]` at dispatch time; it does not change mid-turn.

### 3.3 Reset rules — new commit push resets BOTH loops

When the author pushes a new commit, GitHub sends `pull_request.synchronize` with a new `head.sha`. The sequencer sees the new SHA, finds **no rows** for `(pr_url, new_sha, *, *)`, and starts both stages from turn 1.

Prior-SHA rows are **not deleted** (the audit trail is useful). They are simply orphaned by the new SHA. The dashboard read query filters by `head_sha` = latest, so it naturally shows only the current review.

**Symmetric** (not opencode-only): even if opencode already ran 5 turns on the old SHA, on a new SHA its loop restarts from 1. Reason: the findings are tied to diff content that no longer exists; pretending otherwise would surface stale comments at wrong line numbers.

## 4. Per-turn GitHub identity

### 4.1 Two bot identities

- **opencode posts as `cloglog-opencode-reviewer[bot]`.** Distinct GitHub App, distinct installation token, distinct git user.
- **codex continues to post as `cloglog-codex-reviewer[bot]`** — no change from today.

Neither posts as the human user. The existing author-skip filter in `review_engine.py` (`_BOT_USERNAMES`) is extended to include the opencode bot so that an opencode-authored PR (in principle, future T) is not reviewed by either bot.

### 4.2 Credential storage — `~/.cloglog/credentials`, NOT `.mcp.json`

Per T-214 and the rule in `CLAUDE.md`, bot tokens MUST live in `~/.cloglog/credentials` (0600). Add a new key:

```ini
[opencode_reviewer]
token = <installation-token-from-github-app>
```

`src/gateway/github_token.py::get_opencode_reviewer_token()` reads this key using the same pattern as `get_codex_reviewer_token()`. Env override: `OPENCODE_REVIEWER_TOKEN` (for CI / dev).

The pin test `tests/test_mcp_json_no_secret.py` (see CLAUDE.md) is extended to assert the new token is also absent from `.mcp.json`.

### 4.3 Review body header — visible turn label

Every review body — from either bot — begins with a header line that identifies the reviewer, model, and turn. Example bodies:

```
**opencode (gemma4:e4b) — turn 3/5**

:warning: Missing None guards in request handler.

### Findings
- **[HIGH]** `src/gateway/webhook.py:42` — ...
```

```
**codex (Claude 4.6) — turn 1/2**

:pass: Patch is correct.
```

This header is appended by the sequencer **before** calling `post_review`; the reviewer subprocess doesn't emit it. That keeps the structured JSON schema unchanged and the presentation layer centralized.

## 5. Timeout and failure handling

### 5.1 Per-turn wall-clock budgets

| Stage   | Per-turn timeout       | Rationale |
|---------|------------------------|-----------|
| opencode | `180 s` (configurable via `opencode_turn_timeout_seconds`) | Gemma4:e4b on a workstation GPU produces ~3-10K tokens in 30–90 s for the diffs we see. 180 s gives 2× headroom. Larger would make wedge detection slow; smaller would false-positive on large diffs. |
| codex   | `300 s` (existing `REVIEW_TIMEOUT_SECONDS`)                  | Unchanged. |

Total worst-case wall clock for a non-consensus PR: `5 × 180s + 2 × 300s = 1500 s = 25 min`. That is acceptable for a review (webhook runs out-of-band; merge is not blocked on it). In practice, consensus short-circuits to ~2-3 turns per stage, so realistic wall clock is ~6–8 minutes.

### 5.2 Failure classification — mirrors the project's "Stop on MCP failure" rule

From `CLAUDE.md`:

> - **5xx and 409 are NOT transient and MUST NOT be retried.**
> - **Transient network** (`ECONNRESET`/`ETIMEDOUT`/fetch timeout) → one retry after ≥ 2 s backoff.

Applied per-turn:

- **Subprocess timeout** (opencode or codex exceeded the per-turn budget) → kill, mark turn `timed_out`, drain stderr tail, post skip-comment, **continue** to next turn (not retry — turn N+1 will be a fresh invocation with the same inputs).
- **Ollama API transport error** (opencode only; `ECONNRESET`/`ETIMEDOUT` on the ollama socket) → one ≥2-second backoff retry within the same turn. If the second attempt also fails, mark turn `failed` and continue.
- **Subprocess non-zero exit with no parseable output** → mark turn `failed`, continue.
- **Subprocess non-zero exit WITH parseable JSON** → accept the output (current codex behaviour); log the exit code.
- **Ollama returns 5xx or 409 equivalent** → NOT retried. Mark turn `failed`, continue.

### 5.3 A dead opencode never blocks codex

If all opencode turns fail or time out (an unlucky run: ollama is down, model is unloaded, or the subprocess can't be spawned), the sequencer:

1. Posts one skip-comment on the PR authored by the opencode bot: `SkipReason.OPENCODE_UNAVAILABLE` or `SkipReason.OPENCODE_TIMEOUT`.
2. Logs a structured warning.
3. **Proceeds to codex.** Codex's reviewer prompt does not reference opencode's findings as prerequisites — it is self-contained.

## 6. Resource contention and queuing

### 6.1 One review at a time — reuse the existing outer lock

`ReviewEngineConsumer` already uses an `asyncio.Lock` so only one codex review runs at a time. The new sequencer keeps that lock — one **full two-stage session** at a time.

Reasons:
- Single local GPU. Two parallel gemma4:e4b invocations would contend for ~19GB VRAM on hardware that has 12–16GB; the second would thrash or OOM.
- Serializing also naturally serializes the GitHub API writes, avoiding per-PR review ordering ambiguity.
- Simple.

### 6.2 FIFO queuing — implicit via `asyncio.Lock`

When two PRs arrive within one review window (e.g., two `pull_request.opened` events within 30 s), the webhook dispatcher launches both handlers as `asyncio.create_task`s. Both `await self._lock.acquire()`; Python's `asyncio.Lock` is FIFO-fair by default. So the second PR waits for the first to finish and then proceeds. **No explicit queue data structure needed.**

No dropping, no deferring. Reason: dropping would lose review coverage; deferring would need extra persistence (outside the process) with no clear gain. An in-memory FIFO of at most a handful of PRs at a time is fine.

### 6.3 Rate-limit interaction

`RateLimiter(max_per_hour=10)` (setting: `review_max_per_hour`) is checked **once per full two-stage session** — before stage A starts. It counts sessions, not turns. A PR that triggers all 7 possible turns still counts as 1 against the rate limit.

The per-PR cap (today: `MAX_REVIEWS_PER_PR = 2`) is **re-interpreted**: it counts **sessions**, not review POSTs. Each bot has its own count (uses `count_bot_reviews` split by bot username). So a PR can accumulate up to 2 opencode sessions and 2 codex sessions before the cap trips. A session may post many review POSTs (one per turn) — those are turn count, a separate orthogonal concept tracked in `pr_review_turns`.

## 7. Structured-output contract

### 7.1 Decision — JSON output; reuse `review-schema.json`

Opencode's `--format json` emits a stream of events (JSON lines), not a single final object. That format is unsuitable for review findings. **The opencode prompt explicitly instructs the model to emit a single JSON object matching `review-schema.json` as its final output.** The sequencer post-processes opencode's stdout by extracting the largest `{...}` substring (same fallback already used in `ReviewEngineConsumer._parse_output`, `src/gateway/review_engine.py:848-867`).

No new schema file is created — the existing `.github/codex/review-schema.json` is used for both reviewers. The schema is extended additively with one optional field:

```diff
 {
   "findings": [ ... ],
   "overall_correctness": "...",
-  "overall_explanation": "..."
+  "overall_explanation": "...",
+  "status": "no_further_concerns"   // OPTIONAL — used for consensus detection
 }
```

`additionalProperties: false` at the top level is left as-is (codex-side it was explicit); we relax it to `true` for the opencode path, or (preferred) add `status` to the `properties` map with `"additionalProperties": false` kept. The schema file remains in `.github/codex/`; both reviewers read from it. A future refactor can move it to `.github/review-schema.json` if / when the codex-specific folder outlives its meaning — out of scope for T-248.

### 7.2 Sample opencode invocation

```bash
opencode run \
  --model ollama/gemma4:e4b \
  --format json \
  --log-level ERROR \
  --pure \
  --dangerously-skip-permissions \
  --dir "$PROJECT_ROOT" \
  --print-logs \
  -- \
  "$(cat prompt.md)"
```

The prompt itself is the T-248 opencode review prompt (under `.github/opencode/prompts/review.md`). The last instruction of the prompt reads:

> Your final output MUST be a single JSON object matching this schema and nothing else. Do not wrap it in Markdown code fences. Do not include any prose after the JSON.
>
> ```json
> { ... schema here ... }
> ```

### 7.3 Sample output

```json
{
  "findings": [
    {
      "title": "Missing None guard in request handler",
      "body": "The dict lookup at line 42 does not guard against missing keys; a malformed webhook payload will raise KeyError and the handler returns 500.",
      "confidence_score": 0.85,
      "priority": 2,
      "code_location": {
        "absolute_file_path": "src/gateway/webhook.py",
        "line_range": {"start": 42, "end": 42}
      }
    }
  ],
  "overall_correctness": "patch requires changes",
  "overall_explanation": "One high-severity missing-guard finding; other changes look correct.",
  "status": "review_in_progress"
}
```

### 7.4 Robustness — freeform fallback

If the model (local, freeform) ignores the JSON instruction and writes Markdown, the parser falls back to the existing `_parse_output` logic: extract the largest `{...}` substring, `json.loads` it, validate against `ReviewResult`. If that also fails, the turn is marked `failed` (per §5.2) — no second attempt within the same turn; the next turn will be a fresh subprocess.

## 8. Observability

### 8.1 Structured log lines — one per turn boundary

```jsonc
// On turn start:
{"event":"review_turn_start","stage":"opencode","pr_number":124,"head_sha":"abc1234","turn":2,"max_turns":5}

// On turn end (success):
{"event":"review_turn_end","stage":"opencode","pr_number":124,"head_sha":"abc1234",
 "turn":2,"max_turns":5,"outcome":"completed","finding_count":3,
 "consensus_reached":false,"elapsed_seconds":42.1}

// On turn end (timeout):
{"event":"review_turn_end","stage":"opencode","pr_number":124,"head_sha":"abc1234",
 "turn":2,"max_turns":5,"outcome":"timed_out","elapsed_seconds":180.0,
 "stderr_tail":"..."}

// On stage end:
{"event":"review_stage_end","stage":"opencode","pr_number":124,"head_sha":"abc1234",
 "turns_used":3,"consensus_reached":true,"total_elapsed_seconds":97.4}

// On session end (both stages):
{"event":"review_session_end","pr_number":124,"head_sha":"abc1234",
 "opencode_turns":3,"opencode_consensus":true,
 "codex_turns":1,"codex_consensus":true,
 "total_elapsed_seconds":252.1}
```

### 8.2 Metrics

- `pr_review_turn_duration_seconds{stage, outcome}` — histogram.
- `pr_review_turns_total{stage, outcome}` — counter.
- `pr_review_consensus_turn{stage}` — histogram of the turn index at which consensus was reached (or the cap value, if consensus was not reached; distinguish via a label `reason=consensus|cap`).
- `pr_review_session_duration_seconds` — histogram, end-to-end.

The project does not yet wire Prometheus; these are reserved names in log-only form until it does. Spec records them so the impl lands with consistent naming even if metrics backend comes later.

### 8.3 Task-card badges — extend T-260's `reviewing` surface

T-260 introduced a `reviewing` badge on task cards for PRs under codex review. Extend it: the badge text now includes stage and turn progress, e.g., `opencode 2/5` or `codex 1/2`. When a loop finishes early via consensus, the badge briefly reads `opencode ✓` before the next stage starts.

The dashboard read query:

```sql
SELECT stage, turn_number, consensus_reached
FROM pr_review_turns
WHERE pr_url = :pr_url
  AND head_sha = :head_sha
ORDER BY created_at DESC
LIMIT 1;
```

If the latest row has `consensus_reached=true` or `turn_number = max_turns_for_stage`, the badge shows the next stage's progress (or `done` if both stages are complete). Otherwise the latest `stage N/M` drives the badge text.

## What changes in T-248 — acceptance-criteria deltas

These are the **concrete shifts** to T-248's acceptance criteria that this spec requires. When T-248 opens, its impl plan should cite this list:

1. **Codex is no longer single-pass.** T-248's earlier wording said codex runs after opencode; this spec extends codex to a **2-turn loop** with its own consensus check. The refactor extracts `ReviewLoop` and `Reviewer` so both stages share the loop machinery.
2. **Consensus rule is pinned** — option (c) (explicit flag OR empty-diff). T-248 implements exactly this check; no re-litigation.
3. **`pr_review_turns` table is new.** T-248 writes the Alembic revision (additive only), adds the SQLAlchemy model, imports it in `tests/conftest.py`. Column names, constraints, and indexes are fixed by §3.1 above.
4. **Idempotency via `INSERT ... ON CONFLICT DO NOTHING`** on the `UNIQUE (pr_url, head_sha, stage, turn_number)` index. T-248's test suite MUST exercise webhook re-fire (same delivery-id, same sha) and MUST assert the number of posted reviews equals the number of distinct turns, not the number of webhook deliveries.
5. **New commit push resets both loops** — T-248 tests must cover the `synchronize` event with a new SHA after both stages have already completed on the prior SHA, and assert both stages restart at turn 1.
6. **Two bot identities** — `cloglog-opencode-reviewer[bot]` + `cloglog-codex-reviewer[bot]`. T-248 adds `get_opencode_reviewer_token()` and extends the author-skip filter (`_BOT_USERNAMES`).
7. **Credentials file path** — `~/.cloglog/credentials`, key `opencode_reviewer`. `docs/setup-credentials.md` is updated; the `test_mcp_json_no_secret.py` pin is extended.
8. **Timeout budgets** — opencode 180 s per turn, codex 300 s per turn. Two new settings in `src/shared/config.py` (`opencode_turn_timeout_seconds`, `opencode_max_turns`, `codex_max_turns`).
9. **Rate-limit and per-PR cap semantics change** to count **sessions** (one full two-stage run), not review POSTs. `count_bot_reviews` is split by bot username; T-248 updates the cap check to consult both counts independently.
10. **Review body header is sequencer-owned.** T-248 prepends the `**<bot> (model) — turn N/M**` header inside the sequencer after the reviewer returns, before `post_review`. Reviewer subprocesses emit only the structured JSON.
11. **Opencode prompt file** — add `.github/opencode/prompts/review.md`. Start from `.github/codex/prompts/review.md` and adapt for gemma4:e4b's tendencies (be more explicit about JSON output; remove codex-specific instructions).
12. **Stage A failures never block stage B.** T-248 test suite must include: (a) opencode subprocess unreachable → opencode skip comment posted → codex still runs; (b) opencode all 5 turns time out → codex still runs.
13. **`SkipReason` enum is extended** with `OPENCODE_FAILED`, `OPENCODE_TIMEOUT`, `OPENCODE_UNAVAILABLE` (named separately so dashboards can distinguish; reuse existing skip-comment posting machinery).
14. **Observability log-line shapes are fixed** (§8.1). T-248's tests assert the exact event names and field names emit correctly.

Items explicitly **out of scope** for T-248 (will be separate tasks if pursued):

- GitHub App registration of the opencode bot (operational, not code).
- Prometheus backend wiring for the metric names in §8.2.
- Dashboard frontend work beyond the text of the existing `reviewing` badge.
- Swapping `gemma4:e4b` for a different local model.
- Opinion arbitration / dedup between the two reviewers.

## Open escalations

None. Every one of the 8 T-261 questions has a pinned answer above. If a question **re-opens** during T-248 (e.g., gemma4:e4b turns out not to respect the JSON instruction on 30% of runs), the impl agent MUST escalate via the main-agent inbox, **not** silently invent a decision. This is the "spec is authoritative" rule in the prompt for this worktree.
