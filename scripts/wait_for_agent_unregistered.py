#!/usr/bin/env python3
"""Poll an inbox file for an ``agent_unregistered`` event.

Used by ``close-wave`` and ``reconcile`` skills to implement the cooperative
shutdown wait. The skills call ``mcp__cloglog__request_shutdown`` first, then
invoke this helper. On exit 0 the skill proceeds to tear down the worktree;
on exit 1 it falls back to ``mcp__cloglog__force_unregister``.

See ``docs/design/agent-lifecycle.md`` §2 and §5 for the protocol.

Usage::

    # Capture the inbox size BEFORE calling request_shutdown so a fast agent's
    # agent_unregistered event (which may land before this helper starts) is
    # still observed.
    SINCE=$(stat -c %s "$MAIN_INBOX")
    # … mcp__cloglog__request_shutdown(worktree_id) …
    uv run python scripts/wait_for_agent_unregistered.py \\
        --worktree wt-foo \\
        --inbox "$MAIN_INBOX" \\
        --since-offset "$SINCE" \\
        --timeout 120

Exit codes:
    0 — matching ``agent_unregistered`` event observed
    1 — timeout with no matching event
    2 — inbox path does not exist
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _match(event: dict, worktree: str) -> bool:
    return event.get("type") == "agent_unregistered" and event.get("worktree") == worktree


def wait_for_event(
    inbox: Path,
    worktree: str,
    timeout: float,
    poll_interval: float,
    since_offset: int = 0,
    *,
    clock: callable = time.monotonic,
    sleep: callable = time.sleep,
) -> int:
    """Return 0 if a matching event arrives before ``timeout``, else 1.

    ``since_offset`` is the inbox byte offset the caller captured BEFORE
    issuing ``request_shutdown``. Events at offsets < ``since_offset`` are
    ignored. This closes the race the helper would otherwise have: a fast
    agent can emit ``agent_unregistered`` in the gap between the caller's
    MCP call returning and this helper starting. Snapshotting the inbox
    size at helper entry would drop that event; snapshotting before the
    MCP call is what actually binds the window.

    Default ``since_offset=0`` scans the entire file — safe because the
    caller filters by worktree name and worktree names are not reused
    after teardown (close-wave deletes the branch + worktree row), so a
    pre-existing ``agent_unregistered`` for the requested worktree would
    only appear if that worktree is legitimately shutting down.
    """
    try:
        size_at_entry = inbox.stat().st_size
    except FileNotFoundError:
        print(f"inbox not found: {inbox}", file=sys.stderr)
        return 2

    if since_offset < 0:
        since_offset = 0
    # If the inbox is smaller than since_offset, the file was truncated —
    # scan from the start rather than seeking past the end.
    cursor = min(since_offset, size_at_entry)
    deadline = clock() + timeout

    while True:
        try:
            size = inbox.stat().st_size
        except FileNotFoundError:
            print(f"inbox disappeared: {inbox}", file=sys.stderr)
            return 2

        if size > cursor:
            with inbox.open("rb") as f:
                f.seek(cursor)
                chunk = f.read().decode("utf-8", errors="replace")
            cursor = size
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Corrupt / partial line — skip, do not abort the wait.
                    continue
                if _match(event, worktree):
                    return 0

        if clock() >= deadline:
            return 1
        sleep(poll_interval)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--worktree", required=True, help="Worktree name (e.g. wt-foo)")
    p.add_argument("--inbox", required=True, type=Path, help="Path to main inbox file")
    p.add_argument("--timeout", type=float, default=120.0, help="Total timeout in seconds")
    p.add_argument("--poll-interval", type=float, default=1.0, help="Seconds between stat() polls")
    p.add_argument(
        "--since-offset",
        type=int,
        default=0,
        help=(
            "Inbox byte offset captured BEFORE the caller issued "
            "request_shutdown. Events at offsets < this are ignored. "
            "Default 0 scans the whole file (safe when worktree names are "
            "unique per lifetime)."
        ),
    )
    args = p.parse_args(argv)
    return wait_for_event(
        inbox=args.inbox,
        worktree=args.worktree,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        since_offset=args.since_offset,
    )


if __name__ == "__main__":
    sys.exit(main())
