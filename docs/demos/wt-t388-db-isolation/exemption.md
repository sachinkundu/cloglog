---
verdict: no_demo
diff_hash: 42a73bd663e6097de05fd801440e3a12c09242ccdbafb801c298de75c8339d1a
classifier: demo-classifier
generated_at: 2026-05-03T07:13:44Z
---

## Why no demo

Diff is internal infra plumbing: removes the silent default for DATABASE_URL in
src/shared/config.py and alembic.ini/env.py, adds a `make dev-env` bootstrap
target, hardens scripts/worktree-infra.sh error handling, and adds a pin test.
No HTTP route decorators, MCP tool registrations, frontend components, or
user-read CLI output change — `make dev-env` output is operator/dev tooling,
not a user-facing surface. Strongest `needs_demo` candidate considered was the
Settings change since it can hard-fail backend startup, but that's a config
invariant for operators (caught by ValidationError at import), not a
user-observable behaviour change. If the diff had also altered any `@router`
decorator, an MCP `server.tool` registration, or a frontend route's rendered
output, the verdict would have flipped to `needs_demo`.

## Changed files

- Makefile
- alembic.ini
- docs/invariants.md
- scripts/worktree-infra.sh
- src/alembic/env.py
- src/shared/config.py
- tests/conftest.py
- tests/test_database_url_required.py
