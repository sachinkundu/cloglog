---
verdict: no_demo
diff_hash: 6669037901b995f02cb5ada6218570628be345d0b3c3cada8c7848ce59c2650f
classifier: demo-classifier
generated_at: 2026-05-02T20:35:00Z
---

## Why no demo

Diff is CI/review-pipeline plumbing: `ci.yml` trigger swap
(`synchronize` → `repository_dispatch: codex-finalized`),
`init-smoke.yml` pin routing for workflow-YAML coverage, a new
`dispatch_ci_after_codex` hook in `src/gateway/review_loop.py`, and a
`ci_dispatcher` injection in `review_engine.py`. No HTTP route
decorators, no MCP tool registrations, no React component changes, no
CLI output surface, no DB migrations. Strongest `needs_demo` candidate
was the new function in `src/gateway/review_loop.py`, but it is an
internal hook called from the webhook consumer — no user-observable
surface (operators only notice CI scheduling timing, which is internal
infra). If the diff had added a new `@router` endpoint exposing review
state or changed a frontend status indicator, the classifier would
have flipped to `needs_demo`.

## Changed files

- .github/workflows/ci.yml
- .github/workflows/init-smoke.yml
- CLAUDE.md
- docs/design/ci-codex-trigger.md
- src/gateway/review_engine.py
- src/gateway/review_loop.py
- tests/gateway/test_review_loop_t377_ci_dispatch.py
- tests/plugins/test_ci_workflow_codex_finalized_trigger.py
- tests/plugins/test_init_smoke_ci_workflow.py
