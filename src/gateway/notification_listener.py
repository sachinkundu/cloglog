"""Background listener that creates notifications and dispatches desktop toasts.

T-358 narrows desktop toasts to operator-attention events. Today that means
two rules:

* ``TASK_STATUS_CHANGED -> review`` still creates the persisted ``Notification``
  row + ``NOTIFICATION_CREATED`` SSE so the dashboard bell works, but it does
  NOT shell out to ``notify-send``. With parallel worktrees, a toast on every
  PR opened trains the operator to ignore them.
* ``AGENT_UNREGISTERED`` toasts only when ``data.reason`` is in a small
  allowlist of known non-clean exits (``force_unregistered``,
  ``heartbeat_timeout``). A clean unregister via the public API has no
  ``reason`` and stays silent.

Other operator-attention event classes (``agent_blocked``, repeat
``CHANGES_REQUESTED``, auto-merge stalls, ``close_wave_failed``) do not have
EventBus producers in the current codebase -- they live only in inbox files
and worktree-side scripts. They are deferred until those producers exist;
adding the EventTypes without producers would ship dead dispatch branches.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from uuid import UUID

from src.board.repository import BoardRepository
from src.shared.database import async_session_factory
from src.shared.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)

# AGENT_UNREGISTERED reasons that toast the operator. Anything outside this set
# (including a missing ``reason`` -- the default for clean unregisters via the
# public API) is treated as a routine shutdown and stays silent.
_NONCLEAN_UNREGISTER_REASONS = frozenset({"force_unregistered", "heartbeat_timeout"})


def _read_scalar_from_yaml(config_path: Path, key: str) -> str | None:
    """Stdlib-only YAML scalar reader.

    Mirrors ``plugins/cloglog/hooks/lib/parse-yaml-scalar.sh`` -- top-level
    scalar keys only, strips trailing ``# comment`` and surrounding quotes.
    The python YAML lib is intentionally avoided here so this listener stays
    runnable on hosts where PyYAML is missing from the system interpreter
    (``docs/invariants.md`` hook YAML parsing entry).
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return None
    prefix = f"{key}:"
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :]
        stripped = value.lstrip()
        if not (stripped.startswith("'") or stripped.startswith('"')):
            value = value.split("#", 1)[0]
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value or None
    return None


def _find_project_config() -> Path | None:
    cur = Path.cwd().resolve()
    for parent in [cur, *cur.parents]:
        candidate = parent / ".cloglog" / "config.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_toast_enabled(config_path: Path | None = None) -> bool:
    """Read ``desktop_toast_enabled`` from .cloglog/config.yaml. Default: True.

    Operator off-switch. Restart the gateway to pick up changes -- intended
    as a coarse knob, not hot-reloadable.
    """
    if config_path is None:
        config_path = _find_project_config()
    if config_path is None:
        return True
    raw = _read_scalar_from_yaml(config_path, "desktop_toast_enabled")
    if raw is None:
        return True
    return raw.lower() == "true"


async def _maybe_toast(title: str, body: str, *, enabled: bool) -> None:
    """Best-effort ``notify-send`` invocation.

    Side-effect path identical to the pre-T-358 inline call: gated by
    ``DISPLAY`` and the ``PYTEST_CURRENT_TEST`` guard, ``FileNotFoundError``
    suppressed via ``contextlib.suppress``, ``asyncio.create_subprocess_exec``
    invocation shape unchanged. Only difference: ``enabled`` is the operator
    off-switch from ``.cloglog/config.yaml``.
    """
    if not enabled:
        return
    if not os.environ.get("DISPLAY"):
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with contextlib.suppress(FileNotFoundError):
        await asyncio.create_subprocess_exec(
            "notify-send",
            title,
            body,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )


async def _handle_review_event(event: Event) -> None:
    """Persist a ``Notification`` row + emit ``NOTIFICATION_CREATED``. NO toast.

    T-358: the toast that previously fired here was the noise source. The row
    + SSE remain so the dashboard bell still surfaces the move; only the
    desktop notification is dropped.
    """
    raw_task_id = event.data.get("task_id")
    if not raw_task_id:
        # Cross-worker mirror (T-228) means this listener now sees status-change
        # events from peer workers, demos, and tests too -- not all of them
        # carry a task_id (they predate the notification flow). Skip silently.
        return
    task_id = UUID(raw_task_id)

    async with async_session_factory() as session:
        repo = BoardRepository(session)
        task = await repo.get_task(task_id)
        if task is None:
            logger.warning("Notification listener: task %s not found", task_id)
            return

        notif = await repo.create_notification(
            project_id=event.project_id,
            task_id=task.id,
            task_title=task.title,
            task_number=task.number,
        )

        await event_bus.publish(
            Event(
                type=EventType.NOTIFICATION_CREATED,
                project_id=event.project_id,
                data={
                    "notification_id": str(notif.id),
                    "task_id": str(task.id),
                    "task_title": task.title,
                    "task_number": task.number,
                },
            )
        )


def _agent_unregistered_body(data: dict[str, object]) -> tuple[str, str]:
    reason = str(data.get("reason") or "unknown")
    where = str(data.get("worktree_path") or data.get("worktree_id") or "")
    suffix = f" ({where})" if where else ""
    return ("cloglog", f"Agent unregistered: {reason}{suffix}")


async def _dispatch(event: Event, *, enabled: bool) -> None:
    """Route an event to the right side-effect.

    Stays narrow on purpose -- only the two T-358 rules. Other event types
    are no-ops here; SSE fan-out happens elsewhere.
    """
    if event.type == EventType.TASK_STATUS_CHANGED:
        if event.data.get("new_status") == "review":
            await _handle_review_event(event)
        return
    if event.type == EventType.AGENT_UNREGISTERED:
        reason = event.data.get("reason")
        if reason not in _NONCLEAN_UNREGISTER_REASONS:
            return
        title, body = _agent_unregistered_body(event.data)
        await _maybe_toast(title, body, enabled=enabled)
        return


async def run_notification_listener() -> None:
    """Subscribe to all events and dispatch toasts per the T-358 allowlist."""
    enabled = load_toast_enabled()
    queue = event_bus.subscribe_all()
    try:
        while True:
            event = await queue.get()
            try:
                await _dispatch(event, enabled=enabled)
            except Exception:
                logger.exception("Notification listener error")
    finally:
        event_bus.unsubscribe_all(queue)
