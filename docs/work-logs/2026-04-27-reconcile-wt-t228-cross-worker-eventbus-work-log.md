# Work Log — wt-t228-cross-worker-eventbus

## Task
T-228: Fix prod dashboard auto-refresh — EventBus is per-worker, but prod runs gunicorn with 2 workers.

## Outcome
Merged as PR #233 (squash, 2026-04-26T16:12:43Z).

## Commits on branch
1. `5a96c7c` — fix(eventbus): cross-worker fan-out via Postgres LISTEN/NOTIFY
2. `471196b` — demo(t228): cross-worker EventBus + notification_listener guard
3. `ff86571` — fix(eventbus): scope mirrored events to project subscribers only (codex review #233)

## What changed

### Production code
- **`src/shared/events.py`** — `EventBus.publish()` now mirrors via `pg_notify('cloglog_events', payload)` whenever `configure_cross_worker(dsn)` has been called. A per-process `_source_id` is embedded in the payload to dedupe the publisher's own NOTIFY echo. Background `_listener_loop` reconnects on connection loss with exponential backoff. Mirrored events fan out to project SSE subscribers only — `_global_subscribers` (notification_listener) is fed only by the originating worker's local fan-out, so review→notification creation is single-fire across workers.
- **`src/gateway/app.py`** — Lifespan calls `event_bus.configure_cross_worker(settings.database_url)` and `event_bus.start_listener()` at boot, `event_bus.stop_listener()` at shutdown.
- **`src/gateway/sse.py`** — `_event_generator` yields a `connected` frame the moment a subscriber attaches; `EventSourceResponse` is created with `ping=15` so idle streams emit a keepalive comment every 15s.
- **`src/gateway/notification_listener.py`** — Boy Scout: skip events without `task_id` (latent crash surfaced by the new fan-in).
- **`pyproject.toml`** — `[tool.mypy.overrides]` for `asyncpg.*` (no published py.typed marker).

### Tests
- `tests/shared/test_event_bus_cross_worker.py` (NEW, 5 tests) — pin cross-worker delivery, publisher-echo dedupe, oversize-payload local-only fallback, local-only mode, and the "mirrored events do NOT reach global subscribers" regression added in round 2.
- `tests/gateway/test_sse.py` — added `test_event_generator_emits_initial_connected_frame` and `test_stream_endpoint_configures_periodic_ping`; existing tests adjusted to drain the new initial frame.
- `tests/gateway/test_review_loop_sse_emission.py` — `_Rec` recorder switched from `async put` to `put_nowait` to match the new `_fan_out` API.

### Demo
- `docs/demos/wt-t228-cross-worker-eventbus/` — four-frame proof: cross-worker delivery, publisher-echo dedupe, initial connected SSE frame, and ping-interval wiring. Each DB-using `showboat exec` block sources `scripts/worktree-ports.sh` inline so `showboat verify` works in a clean shell.

## Review history
- Codex round 1 (`:warning:`) — flagged duplicate notifications under --workers 2 (mirrored events reaching `_global_subscribers`) and a hardcoded DB fallback in the demo. Both addressed in `ff86571`.
- Codex round 2 (`:pass:`) — verified against live codebase, traced call sites in app.py / review_loop.py / notification_listener.py, confirmed all behaviours.
- Auto-merge gate: held on `ci_not_green` (e2e-browser pending) → re-evaluated after CI green → merged.

## Quality gate at merge
- 918 passed, 1 xfailed, 88.37% coverage
- Lint, types, contract, demo all green

## Files touched
```
docs/demos/wt-t228-cross-worker-eventbus/demo-script.sh   (new)
docs/demos/wt-t228-cross-worker-eventbus/demo.md          (new, generated)
pyproject.toml
src/gateway/app.py
src/gateway/notification_listener.py
src/gateway/sse.py
src/shared/events.py
tests/gateway/test_review_loop_sse_emission.py
tests/gateway/test_sse.py
tests/shared/__init__.py                                  (new)
tests/shared/test_event_bus_cross_worker.py               (new)
```
