"""Integration tests for /api/v1/agents/close-off-task (T-246).

Real Postgres via conftest fixtures — no mocks. Validates the three
acceptance criteria from the T-246 spec:

1. Launching a worktree files exactly one close-off task assigned to the
   main-agent worktree.
2. Re-calling the endpoint with the same worktree_path is idempotent and
   returns the existing task (``created=false``); no duplicate rows.
3. A PR URL stored against the close-off task's id routes the standard
   webhook primary lookup (``Task.pr_url`` match) back to the main agent.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.repository import BoardRepository
from src.gateway.webhook_consumers import AgentNotifierConsumer
from src.gateway.webhook_dispatcher import WebhookEvent, WebhookEventType


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


async def _register(client: AsyncClient, api_key: str, path: str, branch: str) -> str:
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": path, "branch_name": branch},
        headers=_auth(api_key),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["worktree_id"]


async def _register_with_token(
    client: AsyncClient, api_key: str, path: str, branch: str
) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": path, "branch_name": branch},
        headers=_auth(api_key),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["worktree_id"], body["agent_token"]


async def _create_project(client: AsyncClient, name_suffix: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": f"close-off-{name_suffix}-{uuid.uuid4().hex[:6]}"},
    )
    assert resp.status_code == 201
    payload = resp.json()
    return payload["id"], payload["api_key"]


async def test_create_close_off_task_files_one_task_assigned_to_main_agent(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
) -> None:
    """Worktree creation files exactly one close-off task, owned by the main agent."""
    _, api_key = await _create_project(client, "happy")

    # Main-agent worktree = project root equivalent. The endpoint resolves
    # it from settings.main_agent_inbox_path; wire a fake inbox path for this
    # test — main agent lives at /tmp/main-<rand> and the settings point there.
    main_path = f"/tmp/main-{uuid.uuid4().hex[:8]}"
    wt_path = f"/tmp/wt-foo-{uuid.uuid4().hex[:8]}"

    main_wt_id = await _register(client, api_key, main_path, "main")
    wt_id = await _register(client, api_key, wt_path, "wt-foo")

    from src.shared.config import settings as _settings

    monkeypatch.setattr(_settings, "main_agent_inbox_path", Path(f"{main_path}/.cloglog/inbox"))

    resp = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": wt_path, "worktree_name": "wt-foo"},
        headers=_auth(api_key),
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] is True
    assert body["worktree_id"] == wt_id
    assert body["worktree_name"] == "wt-foo"

    # The task must be owned by the main-agent worktree, not the new
    # worktree — close-off is main's responsibility. Inspect the DB row
    # directly; the agent-scoped tasks endpoint requires an agent token
    # and the project API key doesn't open that door.
    repo = BoardRepository(db_session)
    task = await repo.get_task(uuid.UUID(body["task_id"]))
    assert task is not None
    assert task.worktree_id == uuid.UUID(main_wt_id), (
        f"Close-off task should be assigned to main agent {main_wt_id}; "
        f"got worktree_id={task.worktree_id}"
    )
    assert task.close_off_worktree_id == uuid.UUID(wt_id)
    assert task.status == "backlog"
    assert task.task_type == "task"
    assert "wt-foo" in task.title


async def test_create_close_off_task_is_idempotent(client: AsyncClient) -> None:
    """Re-calling with the same worktree_path returns the existing task."""
    project_id, api_key = await _create_project(client, "idem")
    wt_path = f"/tmp/wt-idem-{uuid.uuid4().hex[:8]}"
    await _register(client, api_key, wt_path, "wt-idem")

    first = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": wt_path, "worktree_name": "wt-idem"},
        headers=_auth(api_key),
    )
    assert first.status_code == 201
    first_body = first.json()
    assert first_body["created"] is True

    second = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": wt_path, "worktree_name": "wt-idem"},
        headers=_auth(api_key),
    )
    assert second.status_code == 201
    second_body = second.json()
    assert second_body["created"] is False, (
        "Re-call must return created=false to signal idempotent hit"
    )
    assert second_body["task_id"] == first_body["task_id"], (
        "Idempotent path must return the SAME task id, not a new row"
    )
    assert second_body["task_number"] == first_body["task_number"]


async def test_create_close_off_task_returns_404_for_unregistered_worktree(
    client: AsyncClient,
) -> None:
    """Calling before the worktree row exists should 404, not create an orphan."""
    _, api_key = await _create_project(client, "unreg")

    resp = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": "/tmp/wt-does-not-exist", "worktree_name": "wt-ghost"},
        headers=_auth(api_key),
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"].lower()
    assert "register_agent" in detail or "not" in detail


async def test_create_close_off_task_reuses_ops_epic_and_feature(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Multiple close-off tasks share the auto-created Operations epic / feature."""
    project_id, api_key = await _create_project(client, "hier")

    wt1 = f"/tmp/wt-a-{uuid.uuid4().hex[:8]}"
    wt2 = f"/tmp/wt-b-{uuid.uuid4().hex[:8]}"
    await _register(client, api_key, wt1, "wt-a")
    await _register(client, api_key, wt2, "wt-b")

    r1 = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": wt1, "worktree_name": "wt-a"},
        headers=_auth(api_key),
    )
    r2 = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": wt2, "worktree_name": "wt-b"},
        headers=_auth(api_key),
    )
    assert r1.status_code == 201 and r2.status_code == 201

    # Confirm only one Operations epic + one Worktree Close-off feature
    # exist for this project — subsequent close-off tasks must reuse.
    epics_resp = await client.get(f"/api/v1/projects/{project_id}/epics")
    epics = epics_resp.json()
    ops_epics = [e for e in epics if e["title"] == "Operations"]
    assert len(ops_epics) == 1, f"Expected exactly 1 Operations epic, got {len(ops_epics)}"
    ops_epic_id = ops_epics[0]["id"]

    feats_resp = await client.get(f"/api/v1/projects/{project_id}/epics/{ops_epic_id}/features")
    feats = feats_resp.json()
    close_off_feats = [f for f in feats if f["title"] == "Worktree Close-off"]
    assert len(close_off_feats) == 1, (
        f"Expected exactly 1 Worktree Close-off feature, got {len(close_off_feats)}"
    )


async def test_webhook_routes_pr_events_to_main_via_task_pr_url(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
    monkeypatch,
) -> None:
    """A PR URL stored on the close-off task routes webhooks via Task.pr_url.

    Exercises the AgentNotifierConsumer primary path end-to-end: the
    close-off task is owned by the main agent worktree, so stamping the
    close-wave PR url on it means the standard primary resolver delivers
    the event into the main agent's inbox file.
    """
    _, api_key = await _create_project(client, "webhook")

    main_inbox_dir = tmp_path / "main-clone"
    main_inbox_dir.mkdir(parents=True)
    (main_inbox_dir / ".cloglog").mkdir()
    main_path = str(main_inbox_dir)

    wt_dir = tmp_path / "wt-x"
    wt_dir.mkdir()
    wt_path = str(wt_dir)

    main_wt_id = await _register(client, api_key, main_path, "main")
    await _register(client, api_key, wt_path, "wt-x")

    from src.shared.config import settings as _settings

    monkeypatch.setattr(_settings, "main_agent_inbox_path", main_inbox_dir / ".cloglog" / "inbox")

    resp = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": wt_path, "worktree_name": "wt-x"},
        headers=_auth(api_key),
    )
    assert resp.status_code == 201
    close_off_task_id = resp.json()["task_id"]

    # Simulate the close-wave agent opening a PR and recording the URL on
    # the close-off task: update the task with pr_url and status=review.
    pr_url = "https://github.com/test-org/test-repo/pull/999"
    patch_resp = await client.patch(
        f"/api/v1/tasks/{close_off_task_id}",
        json={"pr_url": pr_url, "status": "review"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    # Now fire a PR_MERGED webhook event. The primary resolver path should
    # find Task by pr_url → worktree_id → main-agent worktree_path.
    repo = BoardRepository(db_session)
    task = await repo.find_task_by_pr_url(pr_url)
    assert task is not None, "Sanity: close-off task should be findable by PR URL"
    assert task.worktree_id == uuid.UUID(main_wt_id), (
        "Close-off task must be owned by the main agent so the PR event lands "
        "in the main inbox via the primary pr_url match."
    )

    event = WebhookEvent(
        type=WebhookEventType.PR_MERGED,
        delivery_id=uuid.uuid4().hex,
        repo_full_name="test-org/test-repo",
        pr_number=999,
        pr_url=pr_url,
        head_branch="wt-close-2026-04-21-wave-x",
        base_branch="main",
        sender="sachinkundu",
        raw={},
    )

    # Route the event using a session factory bound to the same test DB the
    # HTTP client wrote to. AgentNotifierConsumer writes to the resolved
    # inbox file on success.
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    consumer = AgentNotifierConsumer(session_factory=factory)
    await consumer.handle(event)

    inbox = main_inbox_dir / ".cloglog" / "inbox"
    assert inbox.exists(), "Main-agent inbox should have been written"
    lines = inbox.read_text().strip().splitlines()
    assert lines, "Main-agent inbox should contain at least one event line"
    payload = json.loads(lines[-1])
    assert payload["type"] == "pr_merged"
    assert payload["pr_url"] == pr_url
    assert payload["pr_number"] == 999


async def test_close_off_task_surfaces_in_main_agent_get_tasks(
    client: AsyncClient, monkeypatch
) -> None:
    """T-305 pin: a close-off task filed by the worktree-bootstrap hook must
    surface in the main agent's ``GET /api/v1/agents/{wt}/tasks`` response.

    The 2026-04-26 incident on PR #231 showed the supervisor's
    ``mcp__cloglog__get_my_tasks`` returning zero close-offs even though the
    hook had filed them — diagnosed as the close-off lacking ``worktree_id``
    pointing at the main agent. This pin asserts the documented contract:
    bootstrap → close-off task assigned to main → main agent sees it via
    the agent-scoped tasks endpoint.
    """
    _, api_key = await _create_project(client, "main-sees-close-off")

    main_path = f"/tmp/main-{uuid.uuid4().hex[:8]}"
    wt_path = f"/tmp/wt-pin-{uuid.uuid4().hex[:8]}"

    main_wt_id, main_token = await _register_with_token(client, api_key, main_path, "main")
    await _register(client, api_key, wt_path, "wt-pin")

    from src.shared.config import settings as _settings

    monkeypatch.setattr(_settings, "main_agent_inbox_path", Path(f"{main_path}/.cloglog/inbox"))

    co_resp = await client.post(
        "/api/v1/agents/close-off-task",
        json={"worktree_path": wt_path, "worktree_name": "wt-pin"},
        headers=_auth(api_key),
    )
    assert co_resp.status_code == 201, co_resp.text
    close_off_task_id = co_resp.json()["task_id"]

    # The main agent calls its own /tasks endpoint with its agent token —
    # exactly the path mcp__cloglog__get_my_tasks takes from the supervisor.
    tasks_resp = await client.get(
        f"/api/v1/agents/{main_wt_id}/tasks",
        headers={"Authorization": f"Bearer {main_token}"},
    )
    assert tasks_resp.status_code == 200, tasks_resp.text
    tasks = tasks_resp.json()
    task_ids = [t["id"] for t in tasks]
    assert close_off_task_id in task_ids, (
        "Close-off task must surface in main agent's get_my_tasks "
        f"(got task ids {task_ids}, expected {close_off_task_id})"
    )
    close_off = next(t for t in tasks if t["id"] == close_off_task_id)
    assert close_off["status"] == "backlog", (
        "Close-off must surface as backlog so the supervisor picks it up; "
        f"got status={close_off['status']}"
    )
