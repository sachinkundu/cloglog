"""Background listener that creates notifications and dispatches desktop toasts.

T-358: Desktop toasts are narrowed to operator-attention events only —
``AGENT_BLOCKED``, repeat ``CHANGES_REQUESTED``, auto-merge stall, non-clean
``AGENT_UNREGISTERED``, and ``CLOSE_WAVE_FAILED``. Routine status moves
(``TASK_STATUS_CHANGED -> review``, ``pr_merged``, ``agent_started``) still
create the persisted ``Notification`` row + ``NOTIFICATION_CREATED`` SSE so
the dashboard bell works, but they do NOT shell out to ``notify-send``.

Reason: with parallel worktrees, a toast on every PR opened trains the
operator to ignore them, defeating the alerting model.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from uuid import UUID

from src.board.repository import BoardRepository
from src.shared.database import async_session_factory
from src.shared.events import Event, EventType, event_bus

logger = logging.getLogger(__name__)

# Reasons that count as a clean worktree-agent shutdown -- no toast.
# Anything else (crash, mcp_unavailable, force_unregister, missing reason)
# fires a toast.
_CLEAN_UNREGISTER_REASONS = frozenset({"pr_merged", "no_pr_task_complete"})

_DEFAULT_STALL_MINUTES = 15


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


def load_toast_config(config_path: Path | None = None) -> tuple[bool, int]:
    """Read ``desktop_toast_enabled`` / ``desktop_toast_stall_minutes`` from config.

    Defaults: enabled=True, stall_minutes=15. Returned to ``run_notification_listener``
    once at startup; restart the gateway to pick up changes (the operator
    off-switch is intended as a coarse knob, not hot-reloadable).
    """
    if config_path is None:
        config_path = _find_project_config()
    enabled = True
    stall = _DEFAULT_STALL_MINUTES
    if config_path is None:
        return enabled, stall
    raw_enabled = _read_scalar_from_yaml(config_path, "desktop_toast_enabled")
    if raw_enabled is not None:
        enabled = raw_enabled.lower() == "true"
    raw_stall = _read_scalar_from_yaml(config_path, "desktop_toast_stall_minutes")
    if raw_stall is not None:
        with contextlib.suppress(ValueError):
            stall = int(raw_stall)
    return enabled, stall


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


def _agent_blocked_body(data: dict[str, object]) -> tuple[str, str]:
    reason = data.get("reason") or "blocked"
    where = data.get("worktree_path") or data.get("worktree_id") or ""
    suffix = f" ({where})" if where else ""
    return ("cloglog", f"Agent blocked: {reason}{suffix}")


def _agent_unregistered_body(data: dict[str, object]) -> tuple[str, str]:
    reason = data.get("reason") or "unknown"
    where = data.get("worktree_path") or data.get("worktree_id") or ""
    suffix = f" ({where})" if where else ""
    return ("cloglog", f"Agent unregistered: {reason}{suffix}")


def _changes_requested_body(data: dict[str, object]) -> tuple[str, str]:
    pr = data.get("pr_url") or f"PR #{data.get('pr_number', '?')}"
    return ("cloglog", f"Repeat CHANGES_REQUESTED on {pr} -- operator decision needed")


def _auto_merge_stalled_body(data: dict[str, object]) -> tuple[str, str]:
    pr = data.get("pr_url") or f"PR #{data.get('pr_number', '?')}"
    minutes = data.get("stall_minutes", "?")
    return ("cloglog", f"Auto-merge stalled on {pr} for {minutes} min -- CI not green")


def _close_wave_failed_body(data: dict[str, object]) -> tuple[str, str]:
    branch = data.get("branch") or "<unknown>"
    return ("cloglog", f"close-wave failed on {branch}")


class StallDebouncer:
    """Per-PR ``ci_not_green`` stall tracker.

    The auto-merge gate emits ``ci_not_green`` on every poll while CI is
    pending or red. The first poll is normal; we only want to alert the
    operator when the same PR has been stuck in that state for longer than
    the configured threshold (default 15 min).

    ``record_pending`` returns True exactly once per stall window -- the call
    that crosses the threshold. Subsequent polls return False until ``clear``
    is invoked (when the PR transitions out of the pending state).
    """

    def __init__(self, threshold_seconds: float, *, clock: Callable[[], float] = monotonic) -> None:
        self._threshold = threshold_seconds
        self._clock = clock
        self._first_seen: dict[str, float] = {}
        self._toasted: set[str] = set()

    def record_pending(self, pr_url: str) -> bool:
        now = self._clock()
        first = self._first_seen.setdefault(pr_url, now)
        if pr_url in self._toasted:
            return False
        if now - first >= self._threshold:
            self._toasted.add(pr_url)
            return True
        return False

    def clear(self, pr_url: str) -> None:
        self._first_seen.pop(pr_url, None)
        self._toasted.discard(pr_url)


class ChangesRequestedTracker:
    """Per-PR consecutive-CHANGES_REQUESTED tracker.

    One ``CHANGES_REQUESTED`` is normal -- the agent will auto-fix on the
    next nudge. Two consecutive turns means the agent can't auto-fix and an
    operator decision is needed.

    ``record(pr_url, outcome)`` returns True only when ``outcome`` is
    ``"changes_requested"`` AND the previous recorded outcome for the same
    PR was also ``"changes_requested"``.
    """

    _CR = "changes_requested"

    def __init__(self) -> None:
        self._last: dict[str, str] = {}

    def record(self, pr_url: str, outcome: str) -> bool:
        prev = self._last.get(pr_url)
        self._last[pr_url] = outcome
        return outcome == self._CR and prev == self._CR


async def _dispatch(event: Event, *, enabled: bool) -> None:
    """Route an event to the right side-effect.

    Stays narrow on purpose -- only the allowlisted event classes fire toasts.
    Everything else is a no-op (the dashboard bell pipeline fans out via
    SSE elsewhere).
    """
    if event.type == EventType.TASK_STATUS_CHANGED:
        if event.data.get("new_status") == "review":
            await _handle_review_event(event)
        return
    if event.type == EventType.AGENT_BLOCKED:
        title, body = _agent_blocked_body(event.data)
        await _maybe_toast(title, body, enabled=enabled)
        return
    if event.type == EventType.AGENT_UNREGISTERED:
        reason = event.data.get("reason")
        if reason in _CLEAN_UNREGISTER_REASONS:
            return
        title, body = _agent_unregistered_body(event.data)
        await _maybe_toast(title, body, enabled=enabled)
        return
    if event.type == EventType.CHANGES_REQUESTED_REPEAT:
        title, body = _changes_requested_body(event.data)
        await _maybe_toast(title, body, enabled=enabled)
        return
    if event.type == EventType.AUTO_MERGE_STALLED:
        title, body = _auto_merge_stalled_body(event.data)
        await _maybe_toast(title, body, enabled=enabled)
        return
    if event.type == EventType.CLOSE_WAVE_FAILED:
        title, body = _close_wave_failed_body(event.data)
        await _maybe_toast(title, body, enabled=enabled)
        return


async def run_notification_listener() -> None:
    """Subscribe to all events and dispatch toasts per the T-358 allowlist."""
    enabled, _stall_minutes = load_toast_config()
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
