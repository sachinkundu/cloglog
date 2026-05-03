---
verdict: no_demo
diff_hash: 6c367b5c6ac1eb4aa0a2b90ab9d1647277cff36b0151c58cd16c45ef44ba50dd
classifier: demo-classifier
generated_at: 2026-05-03T00:00:00Z
---

## Why no demo

Signal: changes are confined to backend internals — timeout-scaling
constants and `compute_review_timeout` in `src/gateway/review_engine.py`,
ReviewLoop diagnostics + the T-375 at-most-once posting guard in
`src/gateway/review_loop.py`, a new `emit_codex_review_timed_out`
supervisor inbox event in `webhook_consumers.py`, and a migration
adding nullable `session_index`/`posted_at` columns plus a partial
unique index on `pr_review_turns`. Doc updates (`agent-lifecycle.md`,
setup `SKILL.md`) describe supervisor-agent inbox handling, not
user-facing surfaces. No HTTP route decorators, MCP tool definitions,
frontend components, or CLI outputs are added or changed.
Counter-signal considered: the `AGENT_TIMEOUT` PR comment body now
interpolates the dynamic timeout integer rather than a fixed 300s —
observable to the PR author, but it's a parameter substitution on an
existing surface, not new behaviour. Counterfactual: had the diff
added a new `@router.*` endpoint exposing review-turn state, changed
an MCP tool schema, added a frontend element surfacing
timeout/`session_index`, or introduced a fundamentally new PR comment
shape, I would have flipped to `needs_demo`.

## Changed files

- docs/design/agent-lifecycle.md
- plugins/cloglog/docs/agent-lifecycle.md
- plugins/cloglog/skills/setup/SKILL.md
- src/alembic/versions/894b1085a4d0_add_session_index_and_posted_at_to_pr_review_turns.py
- src/gateway/review_engine.py
- src/gateway/review_loop.py
- src/gateway/webhook_consumers.py
- src/review/interfaces.py
- src/review/models.py
- src/review/repository.py
- tests/gateway/test_review_engine.py
- tests/gateway/test_review_loop.py
- tests/gateway/test_webhook_consumers.py
- tests/review/test_repository.py
