# Demo: CI E2E Pipeline Design Spec (F-29)

This is a documentation-only PR containing a design spec. No executable code was added.

## Spec Location

```
docs/superpowers/specs/2026-04-09-ci-e2e-pipeline.md
```

## Key Decisions

| Decision | Choice |
|----------|--------|
| CI trigger | `pull_request` with path filters |
| Test scope | Full stack: backend + frontend + MCP |
| Required vs advisory | Required (blocks merge) |
| Playwright browser tests | Deferred to follow-up |
| Pre-existing failures | Fix before enabling CI |
| Estimated CI time | ~2 minutes |
