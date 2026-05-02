---
verdict: no_demo
diff_hash: 7f92fd9f80e3250cc39e785fd5b38862f1264d323b3a185cc85400d5b39c1d4c
classifier: demo-classifier
generated_at: 2026-05-02T20:08:00Z
---

## Why no demo

Diff is internal CI plumbing: ci.yml gains a `repository_dispatch` trigger
and check-run mirroring, `src/gateway/review_loop.py` adds
`dispatch_ci_after_codex` and a `ci_dispatcher` hook fired on codex
finalization, and `review_engine.py` wires it in. No HTTP route
decorators, no MCP tool registrations, no frontend changes, no CLI
output changes, no user-observable schema. The strongest `needs_demo`
candidate was the new `dispatch_ci_after_codex` function, but it only
POSTs to GitHub's `repository_dispatch` endpoint — operator-visible only
as a CI timing change, not a stakeholder-facing surface. If the diff had
added or changed a `@router.*` in `src/gateway/**` or modified an MCP
tool's schema, the classifier would have flipped to `needs_demo`.

## Changed files

- .github/workflows/ci.yml
- CLAUDE.md
- docs/design/ci-codex-trigger.md
- src/gateway/review_engine.py
- src/gateway/review_loop.py
- tests/gateway/test_review_loop_t377_ci_dispatch.py
- tests/plugins/test_ci_workflow_codex_finalized_trigger.py
