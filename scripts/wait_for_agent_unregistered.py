#!/usr/bin/env python3
"""Poll an inbox file for an ``agent_unregistered`` event.

Used by ``close-wave`` and ``reconcile`` skills to implement the cooperative
shutdown wait. The skills call ``mcp__cloglog__request_shutdown`` first, then
invoke this helper. On exit 0 the skill proceeds to tear down the worktree;
on exit 1 it falls back to ``mcp__cloglog__force_unregister``.

See ``docs/design/agent-lifecycle.md`` §2 and §5 for the protocol.

Usage::

    uv run python scripts/wait_for_agent_unregistered.py \\
        --worktree wt-foo \\
        --inbox /path/to/.cloglog/inbox \\
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
    *,
    clock: callable = time.monotonic,
    sleep: callable = time.sleep,
) -> int:
    """Return 0 if a matching event arrives before ``timeout``, else 1.

    Only events appended AFTER the call are considered — the helper records
    the inbox size at entry and re-reads from that offset. Skills call
    ``request_shutdown`` immediately before invoking the helper, so any
    pre-existing ``agent_unregistered`` line on the inbox is a stale one from
    a previous session and must not satisfy the wait.
    """
    try:
        initial_size = inbox.stat().st_size
    except FileNotFoundError:
        print(f"inbox not found: {inbox}", file=sys.stderr)
        return 2

    deadline = clock() + timeout
    cursor = initial_size

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
    args = p.parse_args(argv)
    return wait_for_event(
        inbox=args.inbox,
        worktree=args.worktree,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )


if __name__ == "__main__":
    sys.exit(main())
