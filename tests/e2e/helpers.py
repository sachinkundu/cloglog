"""Shared test helpers for E2E tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from httpx import AsyncClient


@dataclass
class ProjectFixture:
    id: str
    api_key: str
    epic_id: str
    feature_id: str
    task_ids: list[str] = field(default_factory=list)


@dataclass
class AgentFixture:
    worktree_id: str
    session_id: str
    agent_token: str = ""


def unique_name(prefix: str = "e2e") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def fake_pr_url() -> str:
    return f"https://github.com/test/e2e-repo/pull/{uuid.uuid4().hex[:8]}"


def auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def mcp_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "X-MCP-Request": "true"}


def agent_auth(token: str) -> dict[str, str]:
    """Auth headers for agent-scoped endpoints."""
    return {"Authorization": f"Bearer {token}", "X-Dashboard-Key": ""}


def dashboard_headers() -> dict[str, str]:
    return {"X-Dashboard-Key": "cloglog-dashboard-dev"}


async def create_project_with_tasks(
    client: AsyncClient,
    n_tasks: int = 3,
    task_types: list[str] | None = None,
) -> ProjectFixture:
    """Create a project with epic > feature > N tasks."""
    project = (
        await client.post(
            "/api/v1/projects",
            json={"name": unique_name(), "description": "E2E test"},
        )
    ).json()
    pid = project["id"]

    epic = (await client.post(f"/api/v1/projects/{pid}/epics", json={"title": "Test Epic"})).json()

    feature = (
        await client.post(
            f"/api/v1/projects/{pid}/epics/{epic['id']}/features",
            json={"title": "Test Feature"},
        )
    ).json()

    types = task_types or ["task"] * n_tasks
    task_ids = []
    for i, tt in enumerate(types):
        task = (
            await client.post(
                f"/api/v1/projects/{pid}/features/{feature['id']}/tasks",
                json={"title": f"Task {i + 1}", "task_type": tt},
            )
        ).json()
        task_ids.append(task["id"])

    return ProjectFixture(
        id=pid,
        api_key=project["api_key"],
        epic_id=epic["id"],
        feature_id=feature["id"],
        task_ids=task_ids,
    )


async def register_agent(
    client: AsyncClient,
    api_key: str,
    worktree_path: str | None = None,
) -> AgentFixture:
    """Register an agent and return its fixture."""
    path = worktree_path or f"/repo/wt-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": path, "branch_name": path.rsplit("/", 1)[-1]},
        headers=auth_headers(api_key),
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    data = resp.json()
    return AgentFixture(
        worktree_id=data["worktree_id"],
        session_id=data["session_id"],
        agent_token=data.get("agent_token", ""),
    )
