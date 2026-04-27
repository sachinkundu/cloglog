# Learnings — wt-t228-cross-worker-eventbus

Durable gotchas worth folding into CLAUDE.md.

## EventBus / cross-worker

- **Postgres `NOTIFY` echoes back to the publishing connection.** Any cross-process pub/sub layered on top of LISTEN/NOTIFY must dedupe by a per-process `source_id` embedded in the payload, or the publisher will see every event twice (once from local fan-out, once from the LISTEN echo). Pin: `tests/shared/test_event_bus_cross_worker.py::test_publisher_does_not_double_deliver_its_own_notify_echo`.

- **Cross-worker mirrors must distinguish "fan out to project subscribers" from "fan out to global subscribers."** A `subscribe_all()` consumer that does write-side work — e.g., `run_notification_listener` inserting a notification row — runs on every gunicorn worker. If a mirrored NOTIFY event is fanned out to global subscribers on each worker, the write-side work executes N times for one logical event (N = worker count). The originating worker is responsible for global delivery via its local fan-out; mirrored events go to project subscribers only. Pin: `test_mirrored_events_do_not_reach_global_subscribers`.

- **Postgres `NOTIFY` payload is capped at 8000 bytes.** Anything larger silently drops at the wire. Cross-worker mirrors must check size client-side, log at WARN with the event type and project_id, and keep local fan-out — degraded delivery (some workers see, none crash) beats an exception that blocks the publishing path. Pin: `test_oversize_payload_is_dropped_locally_logged_no_crash`.

- **SQLAlchemy DSN ≠ asyncpg DSN.** `postgresql+asyncpg://...` is a SQLAlchemy URL; raw `asyncpg.connect()` rejects the `+asyncpg` suffix. Strip it with `url.replace("postgresql+asyncpg://", "postgresql://", 1)` before opening LISTEN/NOTIFY connections.

## SSE / `sse_starlette`

- **`EventSourceResponse(content, ping=N)` is the keepalive knob.** Don't hand-roll a periodic comment yield in the generator; the library has the right hook and emits the comment frame outside the user content stream.

- **SSE wire format uses CRLF; raw curl captures `event: connected\r\n`.** `\r` is invisible in diff output but breaks `showboat verify`'s byte-equality check. Pipe SSE output through `tr -d '\r'` before `grep`-ing for stable capture.

## Showboat / demo gating

- **`showboat verify` re-runs every `exec` block in a clean shell with no `make demo` env.** Two consequences: (1) blocks must not depend on a running backend (HTTP-to-localhost dies on verify), and (2) blocks must not rely on env vars set by the surrounding script — source `scripts/worktree-ports.sh` *inside* the captured command itself if you need `DATABASE_URL` / `BACKEND_PORT`. Hardcoded DSN fallbacks are an anti-pattern; they hide the verify-time gap and break worktrees that override `PG_HOST`/`PG_PORT`.

- **For SSE demos that need the user-observable frame sequence, drive the generator directly.** `_event_generator` is the unit FastAPI streams; calling it from a `python -` block gives the same frame sequence without needing the dev server up. Keeps the proof live without coupling to backend lifecycle.

- **Idempotent get-or-create is required for any `showboat exec` that writes to the DB.** Verify re-runs the block; a second POST against a unique-constrained row blows up. Either GET-then-POST, or use UPSERT semantics — never assume a clean DB.

## Notification listener / cross-worker side-effects

- **A `subscribe_all()` consumer that crashes on a missing field will be amplified by cross-worker fan-in.** Before T-228, `notification_listener` only saw events its own worker published; after T-228, it sees events from every worker, plus tests/demos that publish raw `TASK_STATUS_CHANGED` without a `task_id`. Defensive `event.data.get("task_id")` + early-return is the right fix; the listener is not the right place to enforce schema. Apply the same defensiveness pattern to any other `subscribe_all()` consumer when adding cross-worker mirrors.

## Auto-merge gate / CI ordering

- **Codex `:pass:` can land before CI completes.** The gate's `ci_not_green` branch is the load-bearing wait — `gh pr checks --watch` blocks in-line, then re-evaluates exactly once. Don't expect a "CI succeeded" inbox event; the consumer only emits `ci_failed`.
