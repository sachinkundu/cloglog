---
verdict: no_demo
diff_hash: 410c0ebe08165bd96edd40b8e17fe1a8d1fd7b77bcd9cc58981910717013acdc
classifier: demo-classifier
generated_at: 2026-05-02T14:10:00Z
---

## Why no demo

All changes are internal review-pipeline plumbing: a new JSONB column on
`pr_review_turns`, two new `IReviewTurnRegistry` methods (record / prior
`findings_and_learnings`), a codex prompt-builder that injects PR body +
prior history, `codex_max_turns` dropped from 2 to 1, and updates to the
codex prompt / schema / PR template + bot SKILL doc.

No HTTP route decorators added or changed in `src/**`, no React component
changes (frontend untouched), no MCP server.tool registrations touched,
no CLI stdout surface altered, and the migration adds nullable JSONB
columns invisible to any existing API response.

The strongest `needs_demo` candidate was the schema/prompt change for
codex learnings, but it is an agent-internal review behavior with no
user-facing API or UI surface. Counterfactual: had the diff added a new
`@router.*` endpoint exposing `learnings_json` (e.g., a
`/reviews/:pr/history` route) or surfaced the new column in a frontend
PR-review panel, this would have flipped to `needs_demo` with
`backend-curl` or `frontend-screenshot`.

## Changed files

- .github/codex/prompts/review.md
- .github/codex/review-schema.json
- .github/pull_request_template.md
- docs/design/codex-exhaustive-review.md
- plugins/cloglog/skills/github-bot/SKILL.md
- src/alembic/versions/1574708abb78_add_findings_and_learnings_to_pr_review_.py
- src/gateway/review_engine.py
- src/gateway/review_loop.py
- src/review/interfaces.py
- src/review/models.py
- src/review/repository.py
- src/shared/config.py
- tests/gateway/test_review_engine.py
- tests/gateway/test_review_loop.py
- tests/gateway/test_review_loop_t367_memory.py
- tests/review/test_repository.py
