# Dashboard SSE auto-refresh works under gunicorn --workers 2 — events published on one worker now reach SSE subscribers on every worker.

*2026-04-26T16:02:52Z by Showboat 0.6.1*
<!-- showboat-id: 8a919836-df79-4ca4-b17b-0a68cd40946d -->

Before T-228: each gunicorn worker held its own in-process EventBus. An event published by worker A only reached SSE subscribers attached to worker A — ~50% loss with --workers 2. The proof below stands up two EventBus instances against the same Postgres database (the same shape as two workers in one process group) and asserts that an event published on bus A is delivered to a subscriber on bus B via the new LISTEN/NOTIFY mirror.

```bash
# Source worktree-ports.sh so DATABASE_URL points at this worktree's
# isolated Postgres database in BOTH `make demo` (where run-demo.sh has
# already exported it) and `showboat verify` (which re-runs every exec
# block in a clean shell). PG_HOST/PG_PORT overrides flow through.
source scripts/worktree-ports.sh
uv run --quiet python - <<'PY' 2>&1 | tail -1
import asyncio
import os
from uuid import uuid4

from src.shared.events import Event, EventBus, EventType


async def main() -> str:
    dsn = os.environ["DATABASE_URL"]
    worker_a = EventBus()
    worker_b = EventBus()
    worker_a.configure_cross_worker(dsn)
    worker_b.configure_cross_worker(dsn)
    await worker_a.start_listener()
    await worker_b.start_listener()
    try:
        await asyncio.wait_for(worker_a._listener_ready.wait(), timeout=5.0)
        await asyncio.wait_for(worker_b._listener_ready.wait(), timeout=5.0)
        project_id = uuid4()
        queue_b = worker_b.subscribe(project_id)
        await worker_a.publish(
            Event(
                type=EventType.TASK_STATUS_CHANGED,
                project_id=project_id,
                data={"new_status": "review"},
            )
        )
        event = await asyncio.wait_for(queue_b.get(), timeout=5.0)
        assert event.data["new_status"] == "review"
        return "cross-worker delivery: OK"
    finally:
        await worker_a.stop_listener()
        await worker_b.stop_listener()


print(asyncio.run(main()))
PY
```

```output
cross-worker delivery: OK
```

Postgres delivers NOTIFY back to every LISTEN connection — including the publisher's own. Without dedupe a worker would see each event twice (local fan-out + LISTEN echo). The bus stamps every payload with a per-process source_id and the listener drops echoes that match its own id. The proof below publishes once on a single bus and asserts the local subscriber's queue holds exactly one event after the LISTEN echo window closes.

```bash
source scripts/worktree-ports.sh
uv run --quiet python - <<'PY' 2>&1 | tail -1
import asyncio
import os
from uuid import uuid4

from src.shared.events import Event, EventBus, EventType


async def main() -> str:
    dsn = os.environ["DATABASE_URL"]
    bus = EventBus()
    bus.configure_cross_worker(dsn)
    await bus.start_listener()
    try:
        await asyncio.wait_for(bus._listener_ready.wait(), timeout=5.0)
        project_id = uuid4()
        queue = bus.subscribe(project_id)
        await bus.publish(
            Event(type=EventType.TASK_CREATED, project_id=project_id, data={})
        )
        await asyncio.wait_for(queue.get(), timeout=2.0)
        # Wait for the (would-be-doubled) LISTEN echo and assert nothing arrived.
        await asyncio.sleep(0.5)
        assert queue.empty(), "publisher's own NOTIFY echo was double-delivered"
        return "publisher-echo dedupe: OK"
    finally:
        await bus.stop_listener()


print(asyncio.run(main()))
PY
```

```output
publisher-echo dedupe: OK
```

Secondary fix (same PR): the SSE stream now emits a connected event the moment the subscription completes, instead of staying silent until the first business event arrives. Browsers and proxies see traffic immediately and idle timeouts no longer reap the stream during quiet periods. The proof drives the `_event_generator` directly (the unit FastAPI streams), pulls the first frame, and reports its event name. Generator-direct rather than HTTP because `showboat verify` re-runs every `exec` block in a clean shell with no live backend; the generator IS the user-observable unit so the claim is preserved without coupling the proof to backend lifecycle.

```bash
# Drive the SSE generator directly — backend HTTP would require the dev
# server to be live, but `showboat verify` re-runs every exec block on a
# clean host (no backend, no DB). The generator IS the user-observable
# unit (it's what FastAPI streams), so calling it without the HTTP layer
# preserves the claim and stays verify-safe.
uv run --quiet python - <<'PY' 2>&1 | tail -1
import asyncio
from uuid import uuid4

from src.gateway.sse import _event_generator


async def main() -> str:
    gen = _event_generator(uuid4())
    try:
        first = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    finally:
        await gen.aclose()
    return f"first SSE frame event={first['event']!r}"


print(asyncio.run(main()))
PY
```

```output
first SSE frame event='connected'
```

Without a periodic keepalive, idle SSE streams behind proxies/tunnels can be reaped silently — clients keep the socket open while the server has long since lost it, and the dashboard simply stops auto-refreshing. The endpoint now configures sse_starlette's ping=15s and pins the constant in src/gateway/sse.py. The proof reports the interval value end-to-end so a future refactor that drops the wiring trips this assertion.

```bash
uv run --quiet python -c "
from src.gateway import sse
src_text = __import__('inspect').getsource(sse.stream_events)
ping_wired = 'ping=SSE_PING_INTERVAL_SECONDS' in src_text
print(f'ping_interval_seconds={sse.SSE_PING_INTERVAL_SECONDS} wired={ping_wired}')
"
```

```output
ping_interval_seconds=15 wired=True
```
