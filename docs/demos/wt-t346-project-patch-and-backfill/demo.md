# Operators can repair an empty or non-canonical project repo_url on the cloglog backend by re-running /cloglog init — the backfill round-trips through PATCH /api/v1/projects/{id} and lands canonical bytes.

*2026-04-29T15:49:13Z by Showboat 0.6.1*
<!-- showboat-id: e752758f-f10a-4d35-89bf-9c81f2fd2e43 -->

### Stage 1 — empty-row repair (synthetic fixture)

A project created via the pre-T-346 init flow has `repo_url=""`. The
new `PATCH /api/v1/projects/{id}` route + the `mcp__cloglog__update_project`
MCP tool let `/cloglog init` Step 6a backfill the row using whatever
`git remote get-url origin` returns — even SSH/.git form. The backend
normalizes server-side via `src/board/repo_url.py::normalize_repo_url`.

| Stage | Bytes |
|---|---|
| Before PATCH (broken pre-T-346 state) | `""` |
| Action | `PATCH /api/v1/projects/{id} {"repo_url":"git@github.com:sachinkundu/antisocial.git"}` |
| After PATCH (stored) | `https://github.com/sachinkundu/antisocial` |
| `Project.repo_url.endswith("sachinkundu/antisocial")` | `true` |

This is the exact path that unblocks projects which were created with the
old init flow (the antisocial repair on 2026-04-29 — see T-346 brief).

### Stage 2 — idempotency on already-canonical state

Re-running `/cloglog init` on a project whose `repo_url` is already
canonical writes the same bytes — same input, same stored output. This
matches the antisocial state today (T-346 brief: "no change required —
already canonical").

The repository's `update_project` applies all fields unconditionally
(no `if value is not None` guard, mirroring `update_task` per
CLAUDE.md "Board / task repository"); the route's
`model_dump(exclude_unset=True)` only forwards keys the caller sent,
so an explicit empty string still resets the column to its NOT-NULL
default of `""` without 500-ing on the Postgres
`NotNullViolationError` path.

### Stage 3 — load-bearing surface is pinned

Three presence-pins (`tests/plugins/test_init_repo_url_backfill.py`)
guarantee the SKILL.md keeps:

- `mcp__cloglog__update_project` mention (the MCP tool the backfill
  call routes through),
- the canonical-URL transform (SSH→HTTPS, `.git` strip, trailing-slash
  strip),
- the auto-repair preamble that tells operators what re-running init
  will do.

A fourth parametrized pin compares the SKILL.md bash snippet output
byte-for-byte against `src/board/repo_url.py::normalize_repo_url` for
SSH, `.git`, trailing-slash, and whitespace inputs. Drift between the
shell pre-write and the backend post-write would write different bytes
on each pass; the test catches that before merge.

Plus 16 unit tests on `normalize_repo_url` itself
(`tests/board/test_repo_url.py`) and 6 integration tests on the new
PATCH route + auth shape (`tests/board/test_routes.py`).
