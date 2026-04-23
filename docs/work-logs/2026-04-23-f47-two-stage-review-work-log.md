# Work Log — F-47 Two-Stage PR Review Pipeline

**Close date:** 2026-04-23
**Wave:** wt-f47-two-stage-review (single-agent, two-PR sequence)
**Tasks closed:** T-261 (spec), T-248 (impl)

## Shutdown summary

| Worktree | PRs | Shutdown path | Commits | Notes |
|----------|-----|---------------|---------|-------|
| wt-f47-two-stage-review | #185, #187 | cooperative (agent self-unregistered at 2026-04-23T08:34:51+03:00, before supervisor reached close-wave) | 7 | Agent consumed its own `pr_merged` for #187, called `mark_pr_merged(T-248)`, and exited per §2 protocol. Supervisor close-wave skipped Step 5 and consumed shutdown-artifacts directly. |

**Worktrees left running:** `wt-f48-wave-f` (mid-T-258, do not close).

## Commits brought in

### PR #185 — `docs(f47): two-stage iterative PR review pipeline spec` (merged 2026-04-22T17:18:00Z, commit `489dc8b3b564`)

```
60bb46c docs(f47): address codex review round 2 — DDD boundary + dual-binary startup gate
63ab785 docs(f47): address codex review round 1 — align spec with real codebase
29941c6 docs(f47): two-stage iterative PR review pipeline spec (T-261)
```

### PR #187 — `feat(f47): two-stage iterative PR review pipeline (opencode + codex)` (merged 2026-04-23T05:32:20Z, commit `ac03ecd96611`)

```
3166b21 fix(f47): opencode bot identity, 32K ollama model, verified end-to-end
ddeb2f9 fix(f47): codex review round 2 — DDD boundary, consensus short-circuit on refire, .env.example
a052e0e fix(f47): codex review round 1 — settings→hard-coded, opencode-only gate, post-failure retry
1f140e5 feat(f47): two-stage iterative PR review pipeline (opencode + codex) — T-248
```

## Files changed (PR #187 net)

26 files, **+3603 / −94** lines across both PRs.

New bounded context: `src/review/` (models, interfaces, repository, services, schemas). New Alembic migration `32bcc4c15715_add_pr_review_turns.py`. New `src/gateway/review_loop.py`. Significant additions to `src/gateway/review_engine.py`, `src/gateway/app.py`, `src/gateway/github_token.py`, `src/shared/config.py`. 60 new tests across `tests/review/` and `tests/gateway/`.

Docs: `docs/ddd-context-map.md` (Review subgraph), `docs/setup-credentials.md` (reviewer-bot onboarding + VRAM caveat), `.env.example` (opencode tuning knobs), `.github/opencode/prompts/review.md` (new), `.github/codex/review-schema.json` — `status` enum is **required** per OpenAI Structured Outputs (every property in `properties` must be in `required`) and **nullable** via `"type": ["string", "null"]` with `null` in the enum. T-264 fixed a pre-deployment shape (`status` in `properties` only, not in `required`) that OpenAI 400'd silently; `tests/gateway/test_codex_review_schema.py` now pins the required-and-nullable invariant so a future edit that makes `status` truly optional again fails at `make quality` time instead of at prod webhook time.

Design artifact (from T-261): `docs/design/two-stage-pr-review.md` (~650 lines, answers all 8 spec questions plus 16-item "What changes in T-248" list).

## Feature summary

Two-stage iterative PR reviewer now live:

1. **Stage A — opencode (`cloglog-opencode-reviewer[bot]`, gemma4-e4b-32k local)** runs up to 5 turns, short-circuiting on consensus (persisted-per-turn `consensus_reached` flag, either "no new findings since prior turn" OR explicit `status: "no_further_concerns"` in structured output).
2. **Stage B — codex (`cloglog-codex-reviewer[bot]`, Claude API)** runs after Stage A completes, up to 2 turns, same consensus rules.
3. **Idempotency:** `pr_review_turns` table with unique claim-before-run semantics; webhook redelivery is safe; failed turns retry on next delivery via `reset_to_running` and lowest-failed-turn resume.
4. **Degraded path:** opencode-only hosts supported — codex reviewer gated behind a probe at startup.

## Shutdown-artifact consolidation

The worktree's `shutdown-artifacts/work-log.md` and `shutdown-artifacts/learnings.md` have been inlined into this file and `2026-04-23-f47-two-stage-review-learnings.md` respectively. The artifacts themselves disappear when the worktree is removed in Step 7 of close-wave.

## Verification performed during the session

- `make quality` to green after every commit (15+ times across 6 review rounds).
- End-to-end opencode token chain: JWT → `GET /app` → `GET /app/installations` → `POST access_tokens` (201, 1 h TTL) → `get_opencode_reviewer_token()` returns `ghs_*`.
- End-to-end opencode review run on a real prompt: 15 s wall clock, 100% GPU, 11 GB VRAM, valid JSON output, parses cleanly through `parse_reviewer_output` with severity + status preserved.
- Alembic upgrade → downgrade → upgrade roundtrip on the `pr_review_turns` migration.

## State after this wave

- **In main:** `src/review/` context live; two-stage review pipeline receives webhooks; opencode bot app `cloglog-opencode-reviewer` (App ID 3473952) is installed on the repo; PEM is provisioned at `~/.agent-vm/credentials/opencode-reviewer.pem` (0600); a 32K-context ollama variant is configured on the dev host.
- **Not yet in main:** T-258 (F-48, Option B auth-contract cleanup) is mid-implementation in `wt-f48-wave-f`.
- **Follow-up board tasks created during this wave:** T-262 — enrich agent lifecycle signals (pr_merged_notification to main inbox + PR URLs in agent_unregistered sign-off). Filed against F-48.

## Shutdown path note

**Cooperative shutdown worked end-to-end without supervisor intervention.** The agent:
1. Received `pr_merged` for #187 in its own inbox.
2. Called `mark_pr_merged(T-248)`.
3. `get_my_tasks` returned empty — both assigned tasks terminal.
4. Emitted `agent_unregistered` to `<main>/.cloglog/inbox` with artifact absolute paths.
5. Called `unregister_agent` and exited.

The supervisor observed the unregister event but **initially misread it as "agent exited cleanly" instead of "PR merged + agent exited"** because the current `agent_unregistered` payload carries `tasks_completed: [T-NNN]` without PR URLs. Supervisor had to grep `gh pr list` to reconstruct which PR closed which task. That gap is tracked as T-262 — this close-wave's operational cost is exactly what motivated the task.
