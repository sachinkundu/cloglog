"""Tests for ``scripts/sync_mcp_dist.py`` (T-244).

The script has one filesystem side-effect and one HTTP side-effect. Tests
exercise each in isolation — we do not spawn ``npm`` or the FastAPI app.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sync_mcp_dist.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_mcp_dist", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sync_mcp_dist = _load_module()


# ── extract_tool_names ────────────────────────────────────────────


def test_extract_tool_names_parses_declarations(tmp_path: Path) -> None:
    dist = tmp_path / "server.js"
    dist.write_text(
        """
        server.tool('register_agent', 'doc', {}, async () => {});
        server.tool("get_my_tasks", 'doc', {}, async () => {});
        server.tool(  'start_task',
            'doc', {}, async () => {});
        // someone left a stray string
        const unrelated = 'not_a_tool';
        """,
        encoding="utf-8",
    )
    assert sync_mcp_dist.extract_tool_names(dist) == {
        "register_agent",
        "get_my_tasks",
        "start_task",
    }


def test_extract_tool_names_missing_file_returns_empty(tmp_path: Path) -> None:
    assert sync_mcp_dist.extract_tool_names(tmp_path / "does-not-exist.js") == set()


# ── build_event ───────────────────────────────────────────────────


def test_build_event_shape_is_stable() -> None:
    fixed = datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC)
    event = sync_mcp_dist.build_event({"b_tool", "a_tool"}, {"old_tool"}, now=fixed)
    assert event == {
        "type": "mcp_tools_updated",
        "added": ["a_tool", "b_tool"],
        "removed": ["old_tool"],
        "ts": "2026-04-20T12:00:00+00:00",
    }


# ── broadcast ─────────────────────────────────────────────────────


def test_broadcast_appends_single_line_to_each_existing_parent(tmp_path: Path) -> None:
    main_root = tmp_path / "main"
    worktree = tmp_path / "main" / ".claude" / "worktrees" / "wt-a"
    stale = tmp_path / "main" / ".claude" / "worktrees" / "wt-never-booted"

    (main_root / ".cloglog").mkdir(parents=True)
    (worktree / ".cloglog").mkdir(parents=True)
    # Seed an existing line so we can assert append-not-overwrite.
    (main_root / ".cloglog" / "inbox").write_text("prev\n", encoding="utf-8")

    targets = [
        main_root / ".cloglog" / "inbox",
        worktree / ".cloglog" / "inbox",
        stale / ".cloglog" / "inbox",  # parent does not exist — must be skipped
    ]
    event = {"type": "mcp_tools_updated", "added": ["x"], "removed": [], "ts": "t"}

    written = sync_mcp_dist.broadcast(targets, event)

    assert written == targets[:2]
    main_contents = (main_root / ".cloglog" / "inbox").read_text(encoding="utf-8")
    assert main_contents.splitlines() == ["prev", json.dumps(event, separators=(",", ":"))]
    wt_contents = (worktree / ".cloglog" / "inbox").read_text(encoding="utf-8")
    assert wt_contents.strip() == json.dumps(event, separators=(",", ":"))
    assert not (stale / ".cloglog").exists()


def test_broadcast_creates_inbox_file_when_parent_exists(tmp_path: Path) -> None:
    parent = tmp_path / ".cloglog"
    parent.mkdir()
    target = parent / "inbox"
    assert not target.exists()

    written = sync_mcp_dist.broadcast([target], {"type": "mcp_tools_updated"})

    assert written == [target]
    assert target.read_text(encoding="utf-8").strip() == '{"type":"mcp_tools_updated"}'


# ── inbox_paths_for ────────────────────────────────────────────────


def test_inbox_paths_for_includes_main_plus_each_worktree(tmp_path: Path) -> None:
    paths = sync_mcp_dist.inbox_paths_for(tmp_path, ["/a/wt-1", "/a/wt-2"])
    assert paths == [
        tmp_path / ".cloglog" / "inbox",
        Path("/a/wt-1") / ".cloglog" / "inbox",
        Path("/a/wt-2") / ".cloglog" / "inbox",
    ]


# ── fetch_online_worktree_paths ───────────────────────────────────


def test_fetch_online_worktree_paths_filters_by_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/worktrees")
        return httpx.Response(
            200,
            json=[
                {"status": "online", "worktree_path": "/tmp/wt-a"},
                {"status": "offline", "worktree_path": "/tmp/wt-b"},
                {"status": "online", "worktree_path": "/tmp/wt-c"},
                {"status": "online"},  # missing path — filtered out
            ],
        )

    transport = httpx.MockTransport(handler)
    # httpx.get uses a fresh client, but the module uses httpx.get directly.
    # Override via monkeypatching is overkill — test the function by
    # constructing our own client with the mock transport and patching
    # httpx.get via attribute substitution.
    real_get = httpx.get

    def fake_get(url: str, **kw):  # type: ignore[no-untyped-def]
        with httpx.Client(transport=transport) as c:
            return c.get(url, **kw)

    httpx.get = fake_get
    try:
        paths = sync_mcp_dist.fetch_online_worktree_paths("http://fake", "pid-1")
    finally:
        httpx.get = real_get

    assert paths == ["/tmp/wt-a", "/tmp/wt-c"]


def test_fetch_online_worktree_paths_raises_on_non_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    real_get = httpx.get

    def fake_get(url: str, **kw):  # type: ignore[no-untyped-def]
        with httpx.Client(transport=transport) as c:
            return c.get(url, **kw)

    httpx.get = fake_get
    try:
        with pytest.raises(RuntimeError, match="Expected list"):
            sync_mcp_dist.fetch_online_worktree_paths("http://fake", "pid-1")
    finally:
        httpx.get = real_get


# ── run() end-to-end ──────────────────────────────────────────────


def test_run_is_noop_when_tool_surface_unchanged(tmp_path: Path, capsys) -> None:
    """If pre- and post-build tool sets match, run() skips the broadcast
    even if skip_broadcast is False — no HTTP call needed."""
    root = tmp_path
    (root / "mcp-server" / "dist").mkdir(parents=True)
    dist_server = root / "mcp-server" / "dist" / "server.js"
    dist_server.write_text("server.tool('a', 1);", encoding="utf-8")

    # Bypass the real npm build — the test keeps dist/server.js as-is so
    # old_tools == new_tools.
    rc = sync_mcp_dist.run(
        project_root=root,
        api_url="http://unused",
        project_id="pid",
        skip_build=True,
        skip_broadcast=False,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "tool surface unchanged" in out


def test_run_broadcasts_on_added_tool(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path
    (root / "mcp-server" / "dist").mkdir(parents=True)
    (root / ".cloglog").mkdir()
    dist_server = root / "mcp-server" / "dist" / "server.js"
    # Old tools
    dist_server.write_text("server.tool('old_a', 1);", encoding="utf-8")

    wt_a = root / ".claude" / "worktrees" / "wt-a"
    (wt_a / ".cloglog").mkdir(parents=True)

    # Fake rebuild: write a new dist with an added tool.
    def fake_rebuild(mcp_dir: Path) -> None:
        dist_server.write_text(
            "server.tool('old_a', 1);\nserver.tool('new_b', 1);",
            encoding="utf-8",
        )

    monkeypatch.setattr(sync_mcp_dist, "rebuild_dist", fake_rebuild)
    monkeypatch.setattr(
        sync_mcp_dist,
        "fetch_online_worktree_paths",
        lambda base_url, project_id: [str(wt_a)],
    )

    # Seed a minimal cloglog config the script reads for backend_url/project_id.
    (root / ".cloglog" / "config.yaml").write_text(
        "backend_url: http://fake\nproject_id: pid\n", encoding="utf-8"
    )

    rc = sync_mcp_dist.run(
        project_root=root,
        api_url=None,
        project_id=None,
        skip_build=False,
        skip_broadcast=False,
    )
    assert rc == 0

    main_inbox = (root / ".cloglog" / "inbox").read_text(encoding="utf-8").strip()
    wt_inbox = (wt_a / ".cloglog" / "inbox").read_text(encoding="utf-8").strip()
    main_event = json.loads(main_inbox)
    wt_event = json.loads(wt_inbox)
    assert main_event["type"] == "mcp_tools_updated"
    assert main_event["added"] == ["new_b"]
    assert main_event["removed"] == []
    assert wt_event == main_event
