#!/usr/bin/env python3
"""Rebuild ``mcp-server/dist/`` and broadcast the tool-name diff.

T-244. PR merges that touch ``mcp-server/src/**`` change the MCP tool surface,
but ``mcp-server/dist/`` is gitignored and every worktree's ``.mcp.json`` points
at the *main clone's* compiled artifact. Without this script the main clone's
dist drifts out of sync with main, breaking the next worktree that spawns
(2026-04-19 T-224 → T-225 incident).

Design:
    1. Snapshot tool names declared in ``mcp-server/dist/server.js`` (old set).
    2. Rebuild dist via ``npm run build`` in ``mcp-server/``.
    3. Snapshot tool names again (new set).
    4. Broadcast ``mcp_tools_updated`` with ``added``/``removed`` to every online
       worktree's ``.cloglog/inbox`` + the main agent's inbox.

Invoked by the ``close-wave`` skill after ``git pull origin main`` and by any
main-side helper that post-processes merges. Safe to call when nothing changed:
the broadcast is skipped if ``added``/``removed`` are both empty.

Usage::

    uv run python scripts/sync_mcp_dist.py
    uv run python scripts/sync_mcp_dist.py --skip-build    # only broadcast
    uv run python scripts/sync_mcp_dist.py --skip-broadcast  # only rebuild
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

TOOL_NAME_RE = re.compile(r"""server\.tool\(\s*['"]([a-zA-Z_][a-zA-Z0-9_]*)['"]""")


def extract_tool_names(dist_server_js: Path) -> set[str]:
    """Return the set of MCP tool names declared in a compiled ``server.js``.

    Matches ``server.tool('<name>', ...)`` calls. Returns an empty set if the
    file does not exist yet — the "first build" case.
    """
    if not dist_server_js.exists():
        return set()
    text = dist_server_js.read_text(encoding="utf-8")
    return set(TOOL_NAME_RE.findall(text))


def rebuild_dist(mcp_server_dir: Path) -> None:
    """Run ``npm run build`` inside ``mcp-server/``.

    Raises ``CalledProcessError`` if the build fails — the caller should
    surface that rather than silently broadcasting stale state.
    """
    subprocess.run(
        ["npm", "run", "build"],
        cwd=mcp_server_dir,
        check=True,
    )


def fetch_online_worktree_paths(base_url: str, project_id: str, *, timeout: float = 5.0) -> list[str]:
    """Return absolute paths of worktrees in ``status='online'`` for a project.

    The ``/api/v1/projects/{project_id}/worktrees`` endpoint is public (no
    auth). If the backend is unreachable, raise — the caller decides whether
    to tolerate a missing broadcast or abort.
    """
    resp = httpx.get(f"{base_url}/api/v1/projects/{project_id}/worktrees", timeout=timeout)
    resp.raise_for_status()
    worktrees = resp.json()
    if not isinstance(worktrees, list):
        raise RuntimeError(f"Expected list from /worktrees, got {type(worktrees).__name__}")
    paths: list[str] = []
    for wt in worktrees:
        if wt.get("status") == "online":
            path = wt.get("worktree_path")
            if path:
                paths.append(str(path))
    return paths


def build_event(added: set[str], removed: set[str], *, now: datetime | None = None) -> dict[str, Any]:
    """Assemble the ``mcp_tools_updated`` event body."""
    ts = (now or datetime.now(UTC)).isoformat()
    return {
        "type": "mcp_tools_updated",
        "added": sorted(added),
        "removed": sorted(removed),
        "ts": ts,
    }


def broadcast(inbox_paths: list[Path], event: dict[str, Any]) -> list[Path]:
    """Append ``event`` (as a single JSON line) to each inbox file.

    Returns the list of inboxes that were actually written to. A missing inbox
    file is skipped silently — an agent that hasn't booted yet will not read
    the file and does not need the notification. A missing *parent directory*
    (``.cloglog/`` under the worktree) is also skipped: that means the worktree
    is not a cloglog-managed one.
    """
    line = json.dumps(event, separators=(",", ":")) + "\n"
    written: list[Path] = []
    for inbox in inbox_paths:
        if not inbox.parent.exists():
            continue
        # Create the inbox file if the worktree exists but the file doesn't —
        # that's normal for a freshly-created worktree whose agent hasn't
        # touched it yet. Skip if the parent dir itself is missing.
        with inbox.open("a", encoding="utf-8") as fh:
            fh.write(line)
        written.append(inbox)
    return written


def inbox_paths_for(project_root: Path, worktree_paths: list[str]) -> list[Path]:
    """Return every ``.cloglog/inbox`` target: main root + each worktree."""
    paths: list[Path] = [project_root / ".cloglog" / "inbox"]
    for wt in worktree_paths:
        paths.append(Path(wt) / ".cloglog" / "inbox")
    return paths


def load_project_config(project_root: Path) -> dict[str, Any]:
    """Load ``.cloglog/config.yaml`` for ``backend_url`` / ``project_id``."""
    cfg_path = project_root / ".cloglog" / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"No cloglog config at {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{cfg_path} is not a YAML mapping")
    return data


def run(
    *,
    project_root: Path,
    api_url: str | None,
    project_id: str | None,
    skip_build: bool,
    skip_broadcast: bool,
) -> int:
    mcp_server = project_root / "mcp-server"
    dist_server_js = mcp_server / "dist" / "server.js"

    if not mcp_server.is_dir():
        print(f"  no mcp-server/ under {project_root} — nothing to do", flush=True)
        return 0

    old_tools = extract_tool_names(dist_server_js)

    if not skip_build:
        print(f"  Rebuilding {mcp_server}/dist ...", flush=True)
        rebuild_dist(mcp_server)

    new_tools = extract_tool_names(dist_server_js)
    added = new_tools - old_tools
    removed = old_tools - new_tools

    if not added and not removed:
        print("  mcp-server tool surface unchanged — no broadcast", flush=True)
        return 0

    print(f"  added:   {sorted(added) or '[]'}", flush=True)
    print(f"  removed: {sorted(removed) or '[]'}", flush=True)

    if skip_broadcast:
        print("  --skip-broadcast set — not notifying worktrees", flush=True)
        return 0

    cfg = load_project_config(project_root)
    resolved_url = api_url or cfg.get("backend_url")
    resolved_pid = project_id or cfg.get("project_id")
    if not resolved_url or not resolved_pid:
        print(
            f"  missing backend_url/project_id (config={cfg}, "
            f"cli url={api_url!r}, cli pid={project_id!r})",
            file=sys.stderr,
        )
        return 2

    worktree_paths = fetch_online_worktree_paths(resolved_url, resolved_pid)
    event = build_event(added, removed)
    inboxes = inbox_paths_for(project_root, worktree_paths)
    written = broadcast(inboxes, event)
    print(f"  broadcast to {len(written)} inbox(es):", flush=True)
    for p in written:
        print(f"    {p}", flush=True)
    return 0


def _resolve_project_root(override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Cannot resolve project root: {exc}") from exc
    # --git-common-dir is the path to the main clone's .git directory.
    return Path(out).parent.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project-root", help="Override project root (default: git toplevel)")
    parser.add_argument("--api-url", help="Override backend URL (default: .cloglog/config.yaml)")
    parser.add_argument("--project-id", help="Override project UUID (default: .cloglog/config.yaml)")
    parser.add_argument(
        "--skip-build", action="store_true", help="Skip the rebuild step (broadcast-only)"
    )
    parser.add_argument(
        "--skip-broadcast",
        action="store_true",
        help="Skip the broadcast step (rebuild-only)",
    )
    ns = parser.parse_args(argv)
    root = _resolve_project_root(ns.project_root)
    return run(
        project_root=root,
        api_url=ns.api_url,
        project_id=ns.project_id,
        skip_build=ns.skip_build,
        skip_broadcast=ns.skip_broadcast,
    )


if __name__ == "__main__":
    raise SystemExit(main())
