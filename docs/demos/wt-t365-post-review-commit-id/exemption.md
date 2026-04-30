---
verdict: no_demo
diff_hash: e967890d7bc596c2f2d77d9aed37d3913a94f8041ab32d2d8be64f786923f6e8
classifier: demo-classifier
generated_at: 2026-04-30T00:00:00Z
---

## Why no demo

The diff touches only `src/gateway/review_engine.py` and `src/gateway/review_loop.py` — both are internal plumbing. The change adds an optional `head_sha` parameter to `post_review` and passes it through as `commit_id` in the GitHub API payload; no HTTP route decorator is added or changed, no React component is touched, no MCP tool schema changes, and no CLI output surface is affected. The strongest `needs_demo` candidate considered was the GitHub API payload change (adding `commit_id`), but that is an internal GitHub-to-codex-review-bot detail invisible at the Open Host Service boundary — the PR review response shape seen by cloglog's own API callers is unchanged.

## Changed files

- src/gateway/review_engine.py
- src/gateway/review_loop.py
- tests/gateway/test_review_engine.py
