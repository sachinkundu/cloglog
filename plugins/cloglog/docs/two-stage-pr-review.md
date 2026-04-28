# Two-stage iterative PR review pipeline — design spec

> **Portability note:** This doc is shipped with the cloglog plugin as a reference for the review pipeline design. It contains cloglog-repo-specific cross-references (`docs/ddd-context-map.md`, `docs/contracts/webhook-pipeline-spec.md`, `src/review/`, `src/gateway/`) that are not portable to other projects. Those references document the cloglog implementation and can be ignored when reading this doc as a design pattern for other projects.

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

The implementation will touch exactly these files, and — critically — introduces a new `Review` bounded context (`src/review/`) to hold the turn-accounting table. Per `docs/ddd-context-map.md` and `docs/contracts/webhook-pipeline-spec.md`, **Gateway owns no tables** and the review engine is "a consumer of webhook events and a caller of external APIs [that] does not own any domain models." Placing `pr_review_turns` under `src/gateway/` would violate that boundary; placing it under Board or Agent would conflate pipeline-execution state with task/worktree state. A new supporting context is the right DDD answer (see §3 for the domain, §3.1 for the schema, §3.5 for the context-map update).

| File | Today | Change in T-248 |
|------|-------|-----------------|
| `src/gateway/review_engine.py` | `ReviewEngineConsumer` runs a single codex pass per webhook; `ReviewResult = {verdict, summary, findings}`; `_parse_output` normalizes Codex-schema JSON into exactly those three fields (anything else is discarded). | Refactor into `TwoStageReviewSequencer` that orchestrates two `ReviewLoop` runs (opencode + codex). Extract a `Reviewer` protocol; `CodexReviewer` wraps the current subprocess path; new `OpencodeReviewer` wraps opencode CLI. **Extend `ReviewResult` with an optional `status` field** and update `_parse_output` to carry it through the Codex-schema normalization — otherwise the explicit-consensus branch in §1.1 would silently never fire (see §7.1). **Add `_OPENCODE_BOT` + a `_REVIEWER_BOTS` frozenset** and change the author-skip check in `handles()` from `event.sender == _CODEX_BOT` to `event.sender in _REVIEWER_BOTS`. Do **not** rely on the existing `_BOT_USERNAMES` constant — today it is not referenced from `handles()` at all (§4.1). Sequencer consumes turn-accounting via `IReviewTurnRegistry` (from the new Review context) — never imports `src/review/models.py` or `repository.py` directly. |
| `src/gateway/app.py` (lifespan) | Registers `ReviewEngineConsumer` gated on `is_review_agent_available()`, which only probes `shutil.which(settings.review_agent_cmd)` (one binary). | Replace the existing probe with a **dual-binary probe**: `review_engine_availability()` returns a `(codex_available, opencode_available)` tuple. The sequencer is registered when **at least one** stage can run; otherwise no registration and a loud warning. At registration, both availability flags are logged (including `--version` strings). The sequencer itself receives the flags at construction — if a stage's binary is missing, that stage is skipped at runtime with a single structured warning (not a per-PR skip comment; see §5.4). |
| `src/shared/config.py` | `review_agent_cmd`, `review_max_per_hour`, `review_source_root` | Add `opencode_cmd`, `opencode_model`, `opencode_max_turns`, `codex_max_turns`, `opencode_turn_timeout_seconds`. All optional, all default to sane values listed below. |
| `src/gateway/github_token.py` | `get_github_app_token()` reads `~/.agent-vm/credentials/github-app.pem`; `get_codex_reviewer_token()` reads `~/.agent-vm/credentials/codex-reviewer.pem`; both mint short-lived installation tokens via JWT → `POST /app/installations/{id}/access_tokens`. Hard-coded `_CLAUDE_APP_ID` / `_CODEX_APP_ID` / `_*_INSTALLATION_ID` constants per bot. `~/.cloglog/credentials` is NOT read from this file — that path is reserved for the backend API key (`CLOGLOG_API_KEY`, per T-214). | Add `_OPENCODE_APP_ID`, `_OPENCODE_INSTALLATION_ID`, `_OPENCODE_PEM = Path.home() / ".agent-vm" / "credentials" / "opencode-reviewer.pem"`, `_OPENCODE_PERMISSIONS`, `_opencode_cache`, and `get_opencode_reviewer_token()` — same JWT→installation-token shape as codex. Do NOT place the opencode GitHub token in `~/.cloglog/credentials`. |
| `.github/codex/prompts/review.md`, `review-schema.json` | Prompt + schema for codex | Add `.github/opencode/prompts/review.md` (separate prompt — instructs the local model to emit the same JSON schema). Extend `review-schema.json` additively with one optional top-level `status` property; do NOT fork it. See §7.1. |
| **New context** `src/review/` | — | New bounded context (DDD supporting domain). Owns `PrReviewTurn` model + table. Exposes `IReviewTurnRegistry` interface. Files: `__init__.py`, `models.py`, `interfaces.py`, `repository.py`, `services.py`, `schemas.py`. See §3. |
| `src/alembic/versions/` | Existing revisions | Add an additive migration that creates the `pr_review_turns` table owned by the new `review` context (see §3.1). `down_revision` pins the latest merged revision; use `make db-revision` then rebase if another context merges a revision first. |
| New: `src/gateway/review_loop.py` | — | Houses `ReviewLoop`, `Reviewer` protocol, consensus check. Small — ~120 LOC. Takes `IReviewTurnRegistry` by injection. |
| `tests/conftest.py` | Imports Agent/Board/Document models for `Base.metadata.create_all` | Also import `src.review.models` so `pr_review_turns` is created for tests (T-247 pattern: missing imports here silently break real-DB tests). |
| `tests/test_review_engine.py`, new `tests/test_review_loop.py`, `tests/test_opencode_reviewer.py`, `tests/review/test_repository.py` | — | Real-DB tests for the loop, consensus, idempotency, the opencode adapter, and the Review-context repository. |
| `docs/ddd-context-map.md` | Four contexts: Board, Agent, Document, Gateway | Adds **Review** as a fifth supporting domain with an entry in the mermaid diagram, the relationships table (Gateway → Review = Open Host Service), and the ubiquitous-language glossary. See §3.5. |

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

## 3. Turn accounting and storage — new `Review` bounded context

### 3.0 Why a new bounded context

`docs/ddd-context-map.md` line 31 is explicit: **Gateway owns no tables.** `docs/contracts/webhook-pipeline-spec.md` line 29 restates it for the review engine specifically: "The review engine is a new module within Gateway, not a new bounded context. It is a consumer of webhook events and a caller of external APIs. It does not own any domain models." Persisting `pr_review_turns` "under the review engine" would contradict both rules.

Alternatives evaluated:

- **Extend Board.** Board owns `Project`, `Epic`, `Feature`, `Task`. A review turn is not a board entity; it is keyed by `(pr_url, head_sha)`, not by a `task_id`. A PR can span multiple tasks, and a task can precede any PR at all. Co-locating them would break the "Task is the smallest unit of work" ubiquitous-language invariant.
- **Extend Agent.** Agent owns `Worktree` and `Session`. Turns belong to a PR's lifecycle, not an agent's. No natural home.
- **Keep the state in-memory only.** Violates §3.2 idempotency guarantees and kills §8.3 dashboard surface. Rejected.
- **New Review bounded context.** Introduces a fifth supporting domain dedicated to the PR review pipeline's persisted artifacts. Gateway consumes it via an Open Host Service interface (same pattern as Gateway→Board/Agent/Document).

The new-context option is the architecturally clean answer and the one T-248 implements. The short-term cost is one extra directory and interface file; the long-term benefit is that when a later task adds anything else review-pipeline-specific (structured-output archive, reviewer-latency SLOs, etc.) the home is already there and does not muscle into Board or Gateway.

### 3.1 Schema — `pr_review_turns` (owned by the Review context)

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

`CHECK (stage IN ('opencode', 'codex'))` and `CHECK (status IN ('running','completed','timed_out','failed'))` constraints are added in-migration. Alembic migration is **additive only** per the project rule in `CLAUDE.md` — no data backfill, no destructive cleanup.

The `project_id` FK binds turns to a project so a future project deletion cascades cleanly. The `ON DELETE CASCADE` is intentional — turns are derived artifacts; nothing outside Review references them. All other columns match the original §3.1 design.

### 3.2 Context layout — `src/review/`

```
src/review/
  __init__.py
  models.py         # PrReviewTurn SQLAlchemy model + PrReviewTurnStage / PrReviewTurnStatus StrEnums
  interfaces.py     # IReviewTurnRegistry protocol (what Gateway imports)
  repository.py     # ReviewTurnRepository implementing IReviewTurnRegistry via SQLAlchemy
  services.py       # ReviewTurnService — claim_turn, complete_turn, latest_for, is_consensus_run
  schemas.py        # Pydantic DTOs for dashboard surface (§8.3)
```

`interfaces.py` declares the Protocol the Gateway sequencer depends on:

```python
from typing import Protocol
from uuid import UUID

class IReviewTurnRegistry(Protocol):
    async def claim_turn(
        self,
        project_id: UUID,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
    ) -> bool: ...
    async def complete_turn(
        self,
        *,
        pr_url: str,
        head_sha: str,
        stage: str,
        turn_number: int,
        status: str,
        finding_count: int | None,
        consensus_reached: bool,
        elapsed_seconds: float,
    ) -> None: ...
    async def latest_for(self, pr_url: str, head_sha: str) -> "ReviewTurnSnapshot | None": ...
```

`claim_turn` wraps the `INSERT ... ON CONFLICT DO NOTHING` and returns `True` iff this caller won the slot — the sole synchronization primitive for §3.3 idempotency.

The Gateway sequencer imports ONLY `src.review.interfaces.IReviewTurnRegistry` and receives a concrete instance via dependency injection at `app.py` lifespan setup — it never imports `src.review.models` or `src.review.repository`. Cross-context imports of models/repositories are priority-3 violations by the codex reviewer's own rules.

### 3.3 Idempotency against webhook re-fires

The `UNIQUE (pr_url, head_sha, stage, turn_number)` constraint is the primary guard. The sequencer calls `registry.claim_turn(...)` which internally runs `INSERT ... ON CONFLICT DO NOTHING`. If the insert returns zero rows, **another handler is already running this turn — exit immediately, do not double-post.** This covers:

- GitHub re-delivering the same webhook.
- `webhook_dispatcher` delivery-id dedup failing open (e.g., in-memory set eviction).
- Manual replays from the backend's webhook replay console (future).

`head_sha` is taken from `event.raw["pull_request"]["head"]["sha"]` at dispatch time; it does not change mid-turn.

### 3.4 Reset rules — new commit push resets BOTH loops

When the author pushes a new commit, GitHub sends `pull_request.synchronize` with a new `head.sha`. The sequencer sees the new SHA, `registry.latest_for(pr_url, new_sha)` returns `None`, and both stages start from turn 1.

Prior-SHA rows are **not deleted** (the audit trail is useful). They are simply orphaned by the new SHA. The dashboard read query filters by `head_sha` = latest, so it naturally shows only the current review.

**Symmetric** (not opencode-only): even if opencode already ran 5 turns on the old SHA, on a new SHA its loop restarts from 1. Reason: the findings are tied to diff content that no longer exists; pretending otherwise would surface stale comments at wrong line numbers.

### 3.5 Context-map update

`docs/ddd-context-map.md` gets a new subgraph and new relationship rows:

```diff
 subgraph Gateway["Gateway Context"]
     G1["<b>Application Service</b>"]
     G2["Owns: no tables"]
     G3["Responsibilities:..."]
 end

+subgraph Review["Review Context"]
+    R1["<b>Supporting Domain</b>"]
+    R2["Owns: PrReviewTurn"]
+    R3["Responsibilities:<br/>Turn accounting<br/>Consensus bookkeeping<br/>Idempotent turn claim"]
+end

 Gateway -->|"Open Host Service"| Board
 Gateway -->|"Open Host Service"| Agent
 Gateway -->|"Open Host Service"| Document
+Gateway -->|"Open Host Service"| Review
```

Plus a new relationships-table row: **Review | Gateway | Open Host Service | Gateway calls Review's services through the `IReviewTurnRegistry` interface for turn accounting.** And a new glossary block explaining "Turn," "Stage," and "Consensus" in Review terms.

T-248 updates the context map as part of the same PR — otherwise the next DDD-compliance review will flag a real table without a documented context home.

## 4. Per-turn GitHub identity

### 4.1 Two bot identities

- **opencode posts as `cloglog-opencode-reviewer[bot]`.** Distinct GitHub App, distinct installation token, distinct git user.
- **codex continues to post as `cloglog-codex-reviewer[bot]`** — no change from today.

Neither posts as the human user. The existing author-skip check in `ReviewEngineConsumer.handles()` today is literally `if event.sender == _CODEX_BOT: return False` (`src/gateway/review_engine.py:494-499`). The `_BOT_USERNAMES` constant in the same file is **not** consulted from `handles()` — it exists only as a reference set. T-248 therefore MUST:

- Add `_OPENCODE_BOT: Final = "cloglog-opencode-reviewer[bot]"` next to `_CODEX_BOT`.
- Introduce `_REVIEWER_BOTS: Final = frozenset({_CODEX_BOT, _OPENCODE_BOT})`.
- Change the `handles()` guard to `if event.sender in _REVIEWER_BOTS: return False`.

Do NOT "extend `_BOT_USERNAMES`" — that alone would leave opencode-authored PRs still accepted by `handles()` (since `handles()` never looks at that set) and would let opencode self-trigger review loops. The `_BOT_USERNAMES` constant keeps its existing role (it is the set used by the author-side cap counting and skip-comment gating).

### 4.2 Credential storage — GitHub App PEM at `~/.agent-vm/credentials/opencode-reviewer.pem`

The precedent is the existing reviewer-bot flow in `src/gateway/github_token.py`, not the backend API-key flow:

- `get_github_app_token()` → reads `~/.agent-vm/credentials/github-app.pem` (Claude bot, for code push + PR creation).
- `get_codex_reviewer_token()` → reads `~/.agent-vm/credentials/codex-reviewer.pem` (codex bot, for posting reviews).

Both mint a short-lived installation token via a JWT signed by the PEM and `POST /app/installations/{id}/access_tokens`, with hard-coded `_*_APP_ID` / `_*_INSTALLATION_ID` / `_*_PERMISSIONS` constants in `src/gateway/github_token.py` and an in-memory 50-minute token cache. T-248 adds the **exact same shape** for opencode:

- `_OPENCODE_APP_ID` and `_OPENCODE_INSTALLATION_ID` — hard-coded values from the GitHub App registration (operational step, not code).
- `_OPENCODE_PEM: Final = Path.home() / ".agent-vm" / "credentials" / "opencode-reviewer.pem"`.
- `_OPENCODE_PERMISSIONS = {"contents": "read", "pull_requests": "write"}` (same as codex).
- `_opencode_cache = _TokenCache()`.
- `async def get_opencode_reviewer_token() -> str:` delegating to the shared `_get_token(...)` helper.
- `reset_token_cache()` clears `_opencode_cache` alongside the existing caches.

**`~/.cloglog/credentials` is NOT used for this.** That file is reserved for the backend project API key (`CLOGLOG_API_KEY`, per T-214 and `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md`). Placing an OAuth-style GitHub reviewer token in it would both collide with T-214's single-key convention and require invasive changes to `mcp-server/src/credentials.ts` (which parses that file for a specific key, not multi-section data). The pin test `tests/test_mcp_json_no_secret.py` is about `CLOGLOG_API_KEY` leakage into `.mcp.json`; it is **not** extended by T-248 (no new secret is added to `.mcp.json`'s blast radius).

Operational onboarding for a new host (dev / prod / alt-checkout) mirrors the existing codex onboarding in `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md`:

1. Install the GitHub App on the target repo.
2. Download the App's private key.
3. `chmod 600` + copy to `~/.agent-vm/credentials/opencode-reviewer.pem`.
4. Record the installation-id for the `_OPENCODE_INSTALLATION_ID` constant.

`${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md` is extended to document this step alongside the existing codex-reviewer instructions.

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

### 5.4 Startup-gate behaviour when a binary is missing

Today `src/gateway/app.py:38-47` wires the review consumer behind a single `is_review_agent_available()` probe that only calls `shutil.which(settings.review_agent_cmd)` (the codex binary). A second stage A executable means T-248 must extend this gate — otherwise a host with `codex` installed but `opencode` missing (or misconfigured) boots up "healthy," and every PR then hits 5 stage-A failures before falling through to codex. That is a real deployment-path correctness gap.

The fix:

1. Add `is_opencode_available() -> bool` next to `is_review_agent_available()`. Implementation: `shutil.which(settings.opencode_cmd)` **and** a quick `opencode --version` probe with a 3 s timeout (mirrors `_probe_codex_alive` in `review_engine.py`).
2. At lifespan setup, call both probes. Log one structured line per binary: `{"event":"review_binary_probe","binary":"opencode","available":true,"version":"1.14.20"}`.
3. Registration policy — the probe now produces a triple `(codex_ok, opencode_ok, opencode_enabled)`; an `opencode_effective = opencode_ok AND opencode_enabled` term feeds the decision (T-275):
   | codex | opencode_ok | opencode_enabled | opencode_effective | Action |
   |-------|-------------|-------------------|---------------------|--------|
   | ✓ | ✓ | ✓ | ✓ | Register sequencer with both stages enabled (**two-stage**). |
   | ✓ | ✓ | ✗ | ✗ | Register **codex-only**; an INFO log notes "opencode binary at <cmd> is available but disabled via settings.opencode_enabled — stage A will be skipped." |
   | ✓ | ✗ | — | ✗ | Register **codex-only**. Stage A is a no-op; no PR skip-comment spam. |
   | ✗ | ✓ | ✓ | ✓ | Register **opencode-only**: stage B is a no-op, stage A runs as today. |
   | ✗ | ✓ | ✗ | ✗ | **Do not register.** Same loud ERROR as both-missing — `Review pipeline disabled — no runnable stage (codex_available=false, opencode_available=true, opencode_enabled=false)`. Operators must install codex OR set `OPENCODE_ENABLED=true` in `.env`. |
   | ✗ | ✗ | — | ✗ | **Do not register.** `Review pipeline disabled — no runnable stage (codex_available=false, opencode_available=false, opencode_enabled=...)`. Matches the pre-F-47 no-codex behaviour. |
4. The skipped-mode log emission is **once per session**, not once per turn — otherwise a host with missing opencode would spam one log line per PR-turn per stage A invocation. One line per PR review session at INFO is enough to spot the drift.
5. A new operational doc block (`docs/review-engine-e2e.md` — extend the existing review-engine ops doc) lists the expected startup log lines so oncall can verify both binaries were probed.

The sequencer constructor receives `codex_available: bool, opencode_available: bool` from `app.py`, and the per-session code path skips a stage immediately if its flag is `False`. No code path ever assumes a binary exists — every subprocess launch is guarded.

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

### 7.1 Decision — JSON output; extend `review-schema.json` AND `ReviewResult`

Opencode's `--format json` emits a stream of events (JSON lines), not a single final object. That format is unsuitable for review findings. **The opencode prompt explicitly instructs the model to emit a single JSON object matching `review-schema.json` as its final output.** The sequencer post-processes opencode's stdout by extracting the largest `{...}` substring (same fallback already used in `ReviewEngineConsumer._parse_output`, `src/gateway/review_engine.py:848-867`).

No new schema file is created — the existing `.github/codex/review-schema.json` is used for both reviewers. The schema is extended additively with one optional top-level field:

```diff
 {
   "findings": [ ... ],
   "overall_correctness": "...",
-  "overall_explanation": "..."
+  "overall_explanation": "...",
+  "status": "no_further_concerns"   // OPTIONAL — used for consensus detection
 }
```

Schema-side detail: the current `.github/codex/review-schema.json` enforces `additionalProperties: false` on the top-level object, so unknown fields (including any new `status`) would be rejected by a strict validator. T-248 updates the schema to add `status` to the `properties` map as an optional string (enum — at minimum `"no_further_concerns"` and `"review_in_progress"`) and keeps `additionalProperties: false` intact so schema validation is still strict.

**Schema change is necessary but not sufficient.** The current in-process pipeline is:

1. `ReviewEngineConsumer._parse_output(raw, pr_number)` (`src/gateway/review_engine.py:848-893`) detects Codex-schema JSON (keyed on `"overall_correctness" in data and "verdict" not in data`) and **rewrites** `data` to `{"verdict": ..., "summary": ..., "findings": [...]}` — discarding anything else, including a top-level `status`.
2. That rewritten dict is then validated against the internal `ReviewResult` Pydantic model (`src/gateway/review_engine.py:125-137`), which is declared as exactly `{verdict: str, summary: str, findings: list[ReviewFinding]}`. Extra fields would be ignored by Pydantic defaults even if they survived step 1.

So a reviewer output like `{"status":"no_further_concerns", ...}` is, in the code that ships today, **silently dropped** before reaching any consensus check. The explicit-consensus branch described in §1.1 would never fire, and the loop would always run to its cap. Two independent findings on PR #185 round 1 confirmed this concretely.

T-248 therefore MUST make three correlated changes — not just the schema tweak:

1. **Schema** — add optional top-level `status` (above).
2. **Model** — extend `ReviewResult` with `status: str | None = None` (new field). Validator: if present, must be one of `{"no_further_concerns", "review_in_progress"}`. Absent / `None` = "not yet consensus."
3. **Parser** — update `_parse_output`'s Codex-format normalization so the rewritten dict includes `"status": data.get("status")` (preserve), not just `{verdict, summary, findings}`.

The consensus check in `ReviewLoop` then reads `result.status == "no_further_concerns"` as predicate (a) in §1.1; predicate (b) still runs unconditionally as the belt-and-suspenders check.

Tests (new, under `tests/gateway/test_review_engine.py` and `tests/test_review_loop.py`) assert: (i) a Codex-format payload with `status` set survives the parser, (ii) a Codex-format payload without `status` still parses (backward-compat), (iii) `ReviewLoop` exits on predicate (a), (iv) `ReviewLoop` exits on predicate (b) with predicate (a) absent.

The schema file remains in `.github/codex/`; both reviewers read from it. A future refactor can move it to `.github/review-schema.json` if / when the codex-specific folder outlives its meaning — out of scope for T-248.

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
3. **New `Review` bounded context** (`src/review/`) owns the `pr_review_turns` table. T-248 creates the six files in §3.2, updates `tests/conftest.py` to import the new model, writes the additive Alembic revision, updates `docs/ddd-context-map.md` per §3.5 (mermaid + relationships table + glossary), and ensures the Gateway sequencer imports ONLY `src.review.interfaces.IReviewTurnRegistry` — never `src.review.models` or `src.review.repository`. Column names, constraints, and indexes are fixed by §3.1.
4. **Idempotency via `INSERT ... ON CONFLICT DO NOTHING`** on the `UNIQUE (pr_url, head_sha, stage, turn_number)` index, implemented inside `ReviewTurnRepository.claim_turn`. T-248's test suite MUST exercise webhook re-fire (same delivery-id, same sha) and MUST assert the number of posted reviews equals the number of distinct turns, not the number of webhook deliveries.
5. **New commit push resets both loops** — T-248 tests must cover the `synchronize` event with a new SHA after both stages have already completed on the prior SHA, and assert both stages restart at turn 1.
6. **Two bot identities with a real author-skip fix.** Add `_OPENCODE_BOT = "cloglog-opencode-reviewer[bot]"` alongside `_CODEX_BOT` in `src/gateway/review_engine.py`, introduce `_REVIEWER_BOTS = frozenset({_CODEX_BOT, _OPENCODE_BOT})`, and change the `ReviewEngineConsumer.handles()` guard from `event.sender == _CODEX_BOT` to `event.sender in _REVIEWER_BOTS`. Do NOT rely on the existing `_BOT_USERNAMES` constant — today `handles()` does not consult it (§4.1). Test must assert an `opencode` bot-authored PR is skipped.
7. **Credential path — GitHub App PEM, not `~/.cloglog/credentials`.** T-248 adds `_OPENCODE_APP_ID`, `_OPENCODE_INSTALLATION_ID`, `_OPENCODE_PEM = Path.home() / ".agent-vm" / "credentials" / "opencode-reviewer.pem"`, `_OPENCODE_PERMISSIONS`, `_opencode_cache`, `get_opencode_reviewer_token()`, and extends `reset_token_cache()` in `src/gateway/github_token.py`. `~/.cloglog/credentials` is NOT touched; `tests/test_mcp_json_no_secret.py` is NOT extended (no new secret is added to `.mcp.json`'s blast radius). `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md` documents the PEM provisioning step alongside the existing codex entry.
8. **`ReviewResult` extension and parser preservation.** T-248 extends `ReviewResult` with `status: str | None = None`, updates `_parse_output`'s Codex-schema normalization to carry `status` through (copy from input dict if present), and extends `.github/codex/review-schema.json` additively with an optional top-level `status` enum. Without all three changes, the explicit-consensus predicate (a) in §1.1 is a dead branch — a reviewer that signals `status: no_further_concerns` today would have the field dropped by the existing parser before the loop sees it. Tests assert end-to-end survival of `status` and backward-compatibility when the field is absent.
9. **Timeout budgets** — opencode 180 s per turn, codex 300 s per turn. Three new settings in `src/shared/config.py` (`opencode_turn_timeout_seconds`, `opencode_max_turns`, `codex_max_turns`).
10. **Rate-limit and per-PR cap semantics change** to count **sessions** (one full two-stage run), not review POSTs. `count_bot_reviews` is split by bot username; T-248 updates the cap check to consult both counts independently.
11. **Review body header is sequencer-owned.** T-248 prepends the `**<bot> (model) — turn N/M**` header inside the sequencer after the reviewer returns, before `post_review`. Reviewer subprocesses emit only the structured JSON.
12. **Opencode prompt file** — add `.github/opencode/prompts/review.md`. Start from `.github/codex/prompts/review.md` and adapt for gemma4:e4b's tendencies (be more explicit about JSON output; remove codex-specific instructions).
13. **Stage A failures never block stage B.** T-248 test suite must include: (a) opencode subprocess unreachable → opencode skip comment posted → codex still runs; (b) opencode all 5 turns time out → codex still runs.
14. **`SkipReason` enum is extended** with `OPENCODE_FAILED`, `OPENCODE_TIMEOUT`, `OPENCODE_UNAVAILABLE` (named separately so dashboards can distinguish; reuse existing skip-comment posting machinery).
15. **Observability log-line shapes are fixed** (§8.1). T-248's tests assert the exact event names and field names emit correctly.
16. **Dual-binary startup gate** (§5.4). `src/gateway/app.py` lifespan probes both codex and opencode, emits one `review_binary_probe` log carrying `codex_available / opencode_available / opencode_enabled`, and registers the sequencer under the six-row outcome matrix in §5.4 (post-T-275). A missing binary OR a disabled-by-flag stage at boot is a single ERROR / single-per-session INFO — never per-PR skip-comment spam. Test coverage: (i) both present + flag on → two-stage registered; (ii) codex present, opencode missing → codex-only registered; (iii) codex missing, opencode present, flag on → opencode-only registered; (iv) codex missing, opencode present, **flag off** → NO registration + loud ERROR (T-275 regression guard); (v) both missing → no registration + loud ERROR.

Items explicitly **out of scope** for T-248 (will be separate tasks if pursued):

- GitHub App registration of the opencode bot (operational, not code).
- Prometheus backend wiring for the metric names in §8.2.
- Dashboard frontend work beyond the text of the existing `reviewing` badge.
- Swapping `gemma4:e4b` for a different local model.
- Opinion arbitration / dedup between the two reviewers.

## 9. Per-PR review root resolution (T-278, extended in T-281)

**Originally added 2026-04-23 as part of T-278; extended 2026-04-24 in
T-281 to ship Path 0 (`find_by_pr_url`) and the SHA-check + temp-dir
checkout fallback.** Authoritative — supersedes the pre-T-278 behaviour
where `project_root` was computed once per backend process from
`settings.review_source_root or Path.cwd()`.

### 9.1 Problem statement

T-255 hardened the host-level fallback (`settings.review_source_root` env
var + boot log) so prod no longer silently read prod's stale `main`
checkout via `Path.cwd()`. T-278 made the choice per-PR via a worktree
branch lookup. Two gaps survived into T-281:

1. **Main-agent close-out PRs don't have a worktree keyed by their
   branch.** `/cloglog reconcile` and `/cloglog close-wave` open close-out
   PRs from the main clone. The main agent does NOT spawn a worktree for
   itself — that would cause infinite recursion (each close-out would
   itself need a close-out). T-278's `find_by_branch(project_id,
   head_branch)` returns `None`, the resolver falls back to the host-
   level root, and codex reviews prod's stale `main` tree. Observed as
   false-positive findings on PR #200 and PR #202; both required `make
   promote` as an out-of-band unstick.
2. **SHA drift between any candidate and `event.head_sha` silently
   reviewed the wrong code.** The T-278 "drift warning but still use the
   worktree" policy let codex emit findings referencing files as they
   were on the worktree's HEAD, not as they were on the PR commit GitHub
   is actually asking us to review. Race between push and webhook
   arrival, mid-rebase agent worktree, and prod main-clone lag all
   manifested as the same symptom.

CLAUDE.md's load-bearing rule has two halves: T-255 fixed the host-level
half, T-278 fixed the per-PR choice, T-281 closes the SHA gap between
them.

### 9.2 Resolver contract — `resolve_pr_review_root(event)`

Lives in `src/gateway/review_engine.py`. Invoked by `_review_pr` **per
review**, immediately before constructing `OpencodeReviewer` /
`CodexReviewer`. Signature:

```python
@dataclass(frozen=True)
class PrReviewRoot:
    path: Path
    is_temp: bool = False
    main_clone: Path | None = None  # set when is_temp=True; cleanup anchor


async def resolve_pr_review_root(
    event: WebhookEvent,
    *,
    project_id: UUID,
    worktree_query: IWorktreeQuery,
) -> PrReviewRoot: ...
```

Preference order:

0. **Task pr_url binding (T-281 Path 0).** If there is a `Task` in this
   project whose `pr_url == event.pr_url` and whose `worktree_id` points
   at a known worktree row, return that worktree's path. This follows
   the canonical `tasks.pr_url → task.worktree_id → worktrees.id` join
   — the same chain `webhook_consumers._resolve_agent` uses for routing.
   For main-agent close-out PRs this is the ONLY path that succeeds:
   the close-out task's `worktree_id` is the main agent's own worktree
   row (set by the `start_task` call in the close-out flow), so the
   chain lands on the main clone. For regular agent PRs it resolves to
   the same worktree Path 1 would — same answer, more direct route.

1. **Branch lookup (T-278 Path 1).** Fall through to
   `worktrees.branch_name == event.head_branch` within the project, any
   status. Preserves the T-278 behaviour for the interval between PR
   open and the moment `update_task_status(..., pr_url=...)` is called
   on the task (for both agent and close-out flows).

2. **Host-level fallback (T-255 Path 2).** `settings.review_source_root
   or Path.cwd()`. Used for PRs whose owning worktree is not on this
   host (external contributors, closed worktrees, closed agents).

**SHA-check + temp-dir fallback (T-281).** Whichever candidate the chain
above yields, we probe `git -C <candidate> rev-parse HEAD`. If the
candidate's HEAD disagrees with `event.head_sha`, we attempt
`git worktree add --detach
<main_clone>/.cloglog/review-checkouts/<head_sha[:8]>-<pr_number>
<head_sha>` and return that disposable checkout with `is_temp=True`.
The caller cleans it up via `_remove_review_checkout(main_clone, path)`
in a `finally` block. If the SHA isn't reachable from the main clone
yet, we retry once after `git fetch origin <head_branch>`. If creation
still fails, we fall through to the stale candidate with a
`review_source_drift` warning — a stale worktree reviews better than no
review.

The resolver **never mutates the owning worktree** — no `git fetch` on
it, no `checkout`, no `reset`. The owning agent controls its own
working tree. The temp-dir checkout lives under the main clone's
`.cloglog/review-checkouts/` which is never an agent's worktree.

### 9.3 DDD boundary — Agent context Open Host Service

Gateway must NOT import `src.agent.models` or `src.agent.repository`
(priority-3 DDD violation per `docs/ddd-context-map.md` — Gateway owns
no tables). T-281 extends the T-278 Open Host Service with a second
method; both land inside the same adapter, and Gateway still imports
only the Protocol + factory.

- `src/agent/interfaces.py::IWorktreeQuery` — Protocol with two methods:
  `find_by_branch(project_id, branch_name) -> WorktreeRow | None`
  (T-278) and `find_by_pr_url(project_id, pr_url) -> WorktreeRow | None`
  (T-281).
- `src/agent/interfaces.py::WorktreeRow` — frozen dataclass DTO carried
  across the boundary so Gateway never sees the ORM row.
- `src/agent/services.py::make_worktree_query(session) -> IWorktreeQuery`
  — factory returning a Protocol-typed implementation. The concrete
  adapter is hidden inside the module and composes `AgentRepository`
  + `BoardRepository` internally; Gateway gets one Protocol surface.
- `src/gateway/review_engine.py` imports **only** `IWorktreeQuery`
  (under `TYPE_CHECKING`) and `make_worktree_query` (inside a context-
  manager helper). The `TestReviewEngineDDDBoundary` pin test asserts
  the absence of any other `src.agent.*` import — the "asserting absence
  beats presence" pattern from CLAUDE.md's "Leak-after-fix" rule.

### 9.4 Shared-filesystem invariant

The resolver relies on CLAUDE.md's *"cloglog, the MCP server, and every
worktree agent share one host filesystem. There is no host/VM
filesystem split."* T-281's SHA-check temp-dir fallback extends the
invariant: `<main_clone>/.cloglog/review-checkouts/` is on the same
filesystem as every agent worktree, so `git worktree add --detach` can
materialize the disposable checkout without network I/O for the common
case (SHA already fetched). External-fork PRs are still out of scope
because their HEAD SHA is not reachable from origin of the main clone;
the fetch-retry step fails and the resolver falls through to the stale
candidate.

### 9.5 SHA-check + temp-dir policy

T-281 replaces T-278's "drift warning but proceed" policy with:
*attempt a temp-dir checkout at `event.head_sha`; if that fails, fall
through to the stale candidate with a drift warning*. The failure-
fallback path preserves T-278's "review is better than no review"
invariant while the happy path guarantees codex reads exactly the PR
commit GitHub is asking about. Observable state transitions:

| Condition | Result path | `is_temp` | Log line |
|---|---|---|---|
| pr_url hit + path on disk + SHA matches | Path 0 | False | `review_source=worktree_pr_url …` |
| pr_url hit + path on disk + SHA differs + temp-dir OK | Path 0 → temp | True | `review_source=temp_checkout …` |
| branch hit + SHA matches | Path 1 | False | `review_source=worktree …` |
| branch hit + SHA differs + temp-dir OK | Path 1 → temp | True | `review_source=temp_checkout …` |
| no pr_url, no branch, SHA differs + temp-dir OK | Path 2 → temp | True | `review_source=temp_checkout …` |
| any candidate + SHA differs + temp-dir fails | stale fallthrough | False | `review_source_drift … (temp-dir checkout unavailable)` |

Cleanup is the caller's job: `_review_pr` wraps stages A/B in a
`try/finally` that calls `_remove_review_checkout(main_clone, path)`
when `is_temp=True`. Exceptions in either stage DO NOT skip cleanup —
pinned by `test_review_pr_cleans_up_temp_checkout_on_reviewer_error`.

### 9.6 Out of scope for T-281

- External-fork PRs. Their HEAD SHA is not fetchable via
  `git fetch origin <head_branch>` (branch lives on the fork's remote,
  not origin). Rather than plumb per-PR `refs/pull/<N>/head` fetching,
  T-281 deliberately falls through to the host fallback + drift
  warning. File a follow-up if external-fork review quality becomes a
  pressing concern; `uploadpack.allowAnySHA1InWant` +
  `fetch <fork-url> <sha>` is the known direction.
- Full cloud-VM mode (Railway, containerised agents with their own
  filesystem). T-281 still assumes the host-shared-filesystem invariant
  for the main clone's `.cloglog/review-checkouts/` path.
- `_fetch_pr_diff` is unchanged — diff-fetch from GitHub is already
  per-PR and correct.
- `pr_review_turns`, the consensus predicate, and turn-level
  persistence are untouched.
- Opencode (currently disabled via `settings.opencode_enabled=False`
  per T-275) is unchanged; when re-enabled it will share the same
  per-PR `project_root` via the single resolver call in `_review_pr`.
- `settings.review_source_root` and `resolve_review_source_root()`
  remain in place — they are the host-level fallback + the startup-log
  path, AND the parent path for the temp-dir checkout directory in
  T-281. Deleting them would silently re-break T-255 on hosts that
  have no matching worktree for a given PR.

## Open escalations

None. Every one of the 8 T-261 questions has a pinned answer above. If a question **re-opens** during T-248 (e.g., gemma4:e4b turns out not to respect the JSON instruction on 30% of runs), the impl agent MUST escalate via the main-agent inbox, **not** silently invent a decision. This is the "spec is authoritative" rule in the prompt for this worktree.
