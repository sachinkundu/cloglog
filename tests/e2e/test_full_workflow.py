"""E2E test: complete end-to-end workflow.

Exercises the full flow across all bounded contexts in a single test:
project creation → epic/feature/task setup → agent registers →
agent starts task → document attached → agent completes task →
board reflects final state → auth works throughout.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_full_workflow(client: AsyncClient) -> None:
    """Complete workflow crossing all bounded contexts."""

    # ── 1. Create project (Board context) ────────────────────
    project = (
        await client.post(
            "/api/v1/projects",
            json={
                "name": f"workflow-{uuid.uuid4().hex[:8]}",
                "description": "Full E2E workflow test",
                "repo_url": "https://github.com/test/repo",
            },
        )
    ).json()
    pid = project["id"]
    api_key = project["api_key"]
    assert project["status"] == "active"

    # ── 2. Verify auth works (Gateway context) ───────────────
    # /gateway/me needs both MCP-level access (to pass middleware for non-agent route)
    # and an API key (for CurrentProject dependency)
    auth_headers = {"Authorization": f"Bearer {api_key}", "X-MCP-Request": "true"}
    me = (await client.get("/api/v1/gateway/me", headers=auth_headers)).json()
    assert me["id"] == pid

    # ── 3. Import plan with epics/features/tasks (Board) ─────
    import_resp = await client.post(
        f"/api/v1/projects/{pid}/import",
        json={
            "epics": [
                {
                    "title": "Core Backend",
                    "bounded_context": "board",
                    "features": [
                        {
                            "title": "Project Management",
                            "tasks": [
                                {"title": "Create models", "priority": "high"},
                                {"title": "Create routes", "priority": "high"},
                                {"title": "Write tests", "priority": "normal"},
                            ],
                        },
                        {
                            "title": "Task Workflow",
                            "tasks": [
                                {"title": "Status transitions", "priority": "high"},
                            ],
                        },
                    ],
                },
                {
                    "title": "Agent System",
                    "bounded_context": "agent",
                    "features": [
                        {
                            "title": "Registration",
                            "tasks": [
                                {"title": "Register endpoint", "priority": "high"},
                            ],
                        },
                    ],
                },
            ]
        },
    )
    assert import_resp.status_code == 201
    counts = import_resp.json()
    assert counts["epics_created"] == 2
    assert counts["features_created"] == 3
    assert counts["tasks_created"] == 5

    # ── 4. Verify board shows all tasks in backlog ───────────
    board = (await client.get(f"/api/v1/projects/{pid}/board")).json()
    assert board["total_tasks"] == 5
    assert board["done_count"] == 0

    backlog_col = next(c for c in board["columns"] if c["status"] == "backlog")
    assert len(backlog_col["tasks"]) == 5

    # Grab a task to work on
    target_task = backlog_col["tasks"][0]
    task_id = target_task["id"]

    # ── 5. Agent registers (Agent context) ───────────────────
    reg = (
        await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": "/repo/wt-board", "branch_name": "wt-board"},
            headers=auth_headers,
        )
    ).json()
    wt_id = reg["worktree_id"]
    assert reg["resumed"] is False

    # Verify worktree is listed
    worktrees = (await client.get(f"/api/v1/projects/{pid}/worktrees")).json()
    assert any(wt["id"] == wt_id for wt in worktrees)

    # ── 6. Assign and start task ─────────────────────────────
    await client.patch(
        f"/api/v1/tasks/{task_id}",
        json={"status": "assigned", "worktree_id": wt_id},
    )

    start = (
        await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": task_id})
    ).json()
    assert start["status"] == "in_progress"

    # ── 7. Heartbeat while working ───────────────────────────
    hb = (await client.post(f"/api/v1/agents/{wt_id}/heartbeat")).json()
    assert hb["status"] in ("online", "ok")

    # ── 8. Attach a document to the task (Document context) ──
    doc = (
        await client.post(
            "/api/v1/documents",
            json={
                "title": "Implementation Notes",
                "content": "## Notes\nImplemented using SQLAlchemy models.",
                "doc_type": "notes",
                "source_path": "docs/impl-notes.md",
                "attached_to_type": "task",
                "attached_to_id": task_id,
            },
        )
    ).json()
    assert doc["attached_to_id"] == task_id

    # Verify document is retrievable filtered by task
    task_docs = (
        await client.get(
            "/api/v1/documents",
            params={"attached_to_type": "task", "attached_to_id": task_id},
        )
    ).json()
    assert len(task_docs) == 1
    assert task_docs[0]["title"] == "Implementation Notes"

    # ── 9. Move task to review (agents cannot complete tasks) ──
    import uuid as _uuid

    pr_url = f"https://github.com/test/repo/pull/{_uuid.uuid4().hex[:8]}"
    review_resp = await client.patch(
        f"/api/v1/agents/{wt_id}/task-status",
        json={"task_id": task_id, "status": "review", "pr_url": pr_url},
    )
    assert review_resp.status_code == 204

    # Dashboard marks done
    done_resp = await client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done"})
    assert done_resp.status_code == 200

    # ── 10. Board reflects the status change ─────────────────
    board_after = (await client.get(f"/api/v1/projects/{pid}/board")).json()
    assert board_after["done_count"] == 1

    done_col = next(c for c in board_after["columns"] if c["status"] == "done")
    done_ids = [t["id"] for t in done_col["tasks"]]
    assert task_id in done_ids

    # ── 11. Unregister agent ─────────────────────────────────
    unreg = await client.post(f"/api/v1/agents/{wt_id}/unregister")
    assert unreg.status_code == 204

    # ── 12. Attach a project-level document ──────────────────
    project_doc = (
        await client.post(
            "/api/v1/documents",
            json={
                "title": "Project Summary",
                "content": "Phase 1 complete.",
                "doc_type": "summary",
                "attached_to_type": "project",
                "attached_to_id": pid,
            },
        )
    ).json()
    assert project_doc["attached_to_type"] == "project"

    # Verify project docs are filterable
    proj_docs = (
        await client.get(
            "/api/v1/documents",
            params={"attached_to_type": "project", "attached_to_id": pid},
        )
    ).json()
    assert len(proj_docs) >= 1
