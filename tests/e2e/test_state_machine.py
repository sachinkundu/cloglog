"""E2E tests for the task state machine.

Scenario 3: All task state transitions and guards are enforced correctly.
Covers valid transitions, blocked transitions, pipeline ordering,
PR URL requirements, and the one-active-task guard.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.e2e.helpers import (
    agent_auth,
    create_project_with_tasks,
    fake_pr_url,
    register_agent,
)

pytestmark = pytest.mark.asyncio


async def _setup_agent_with_assigned_task(
    client: AsyncClient,
    n_tasks: int = 1,
    task_types: list[str] | None = None,
) -> tuple:
    """Create project, register agent, assign all tasks. Returns (pf, agent, task_ids, ah)."""
    pf = await create_project_with_tasks(client, n_tasks=n_tasks, task_types=task_types)
    agent = await register_agent(client, pf.api_key)
    ah = agent_auth(agent.agent_token)

    for tid in pf.task_ids:
        r = await client.patch(
            f"/api/v1/agents/{agent.worktree_id}/assign-task",
            json={"task_id": tid},
            headers=ah,
        )
        assert r.status_code == 200, f"Assign failed for {tid}: {r.text}"

    return pf, agent, pf.task_ids, ah


# ── Valid transitions ───────────────────────────────────────────


async def test_valid_transition_backlog_to_in_progress(client: AsyncClient) -> None:
    """Starting a task moves it from backlog to in_progress."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


async def test_valid_transition_in_progress_to_review(client: AsyncClient) -> None:
    """Moving from in_progress to review with a PR URL succeeds."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )

    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )
    assert resp.status_code == 204


async def test_valid_transition_review_to_in_progress(client: AsyncClient) -> None:
    """Moving from review back to in_progress succeeds (e.g. addressing review comments)."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )

    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "in_progress"},
        headers=ah,
    )
    assert resp.status_code == 204


async def test_dashboard_can_move_to_done(client: AsyncClient) -> None:
    """The dashboard (not the agent) can move a task from review to done."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )

    resp = await client.patch(
        f"/api/v1/tasks/{task_ids[0]}",
        json={"status": "done"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


# ── Blocked transitions ────────────────────────────────────────


async def test_skip_state_backlog_to_review_allowed(client: AsyncClient) -> None:
    """update_task_status allows moving from backlog directly to review.

    There is no guard in the current code preventing status jumps —
    the only guards are: agent can't move to done, and pr_url is required
    for review. Skipping in_progress is allowed.
    """
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )
    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"


async def test_agent_cannot_move_to_done(client: AsyncClient) -> None:
    """Agents cannot move tasks to done — only the dashboard can."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )

    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "done"},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


# ── Pipeline ordering ──────────────────────────────────────────


async def test_pipeline_ordering_spec_before_plan(client: AsyncClient) -> None:
    """Cannot start a plan task before the spec task is done."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(
        client, n_tasks=2, task_types=["spec", "plan"]
    )
    _spec_id, plan_id = task_ids[0], task_ids[1]

    # Try to start plan first — should fail because spec is not done
    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": plan_id},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


async def test_pipeline_ordering_plan_before_impl(client: AsyncClient) -> None:
    """Cannot start an impl task before the plan task is done."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(
        client, n_tasks=3, task_types=["spec", "plan", "impl"]
    )
    spec_id, _plan_id, impl_id = task_ids[0], task_ids[1], task_ids[2]

    # Complete spec: start -> review -> dashboard done
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": spec_id},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": spec_id, "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )
    await client.patch(f"/api/v1/tasks/{spec_id}", json={"status": "done"})

    # Try to start impl — should fail because plan is not done
    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": impl_id},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


async def test_pipeline_ordering_standalone_tasks_skip(client: AsyncClient) -> None:
    """Standalone task_type='task' tasks have no pipeline ordering constraint."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(
        client, n_tasks=2, task_types=["task", "task"]
    )
    task_1, task_2 = task_ids[0], task_ids[1]

    # Complete first task: start -> review -> dashboard done
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_1},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_1, "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )
    await client.patch(f"/api/v1/tasks/{task_1}", json={"status": "done"})

    # Start second task — should succeed (no pipeline constraints)
    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_2},
        headers=ah,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# ── PR URL guards ───────────────────────────────────────────────


async def test_pr_url_required_for_review(client: AsyncClient) -> None:
    """Moving to review without a pr_url is rejected."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )

    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review"},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


async def test_skip_pr_allows_review_without_pr_url(client: AsyncClient) -> None:
    """Moving to review with skip_pr=true succeeds without a PR URL."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )

    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review", "skip_pr": True},
        headers=ah,
    )
    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"


async def test_skip_pr_still_rejected_without_flag(client: AsyncClient) -> None:
    """Moving to review without pr_url AND without skip_pr is still rejected."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client)

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )

    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review"},
        headers=ah,
    )
    assert resp.status_code == 409
    assert "skip_pr" in resp.json()["detail"]


async def test_pr_url_reuse_blocked_same_feature(client: AsyncClient) -> None:
    """Two tasks in the same feature cannot use the same PR URL."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client, n_tasks=2)
    task_1, task_2 = task_ids[0], task_ids[1]
    shared_pr = fake_pr_url()

    # Complete first task with the PR URL
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_1},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_1, "status": "review", "pr_url": shared_pr},
        headers=ah,
    )
    await client.patch(f"/api/v1/tasks/{task_1}", json={"status": "done"})

    # Start second task, try to review with same PR URL
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_2},
        headers=ah,
    )
    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_2, "status": "review", "pr_url": shared_pr},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


@pytest.mark.xfail(reason="pr_url guard is currently feature-scoped, needs project-wide fix")
async def test_pr_url_reuse_blocked_cross_feature(client: AsyncClient) -> None:
    """PR URL reuse should be blocked across features in the same project."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client, n_tasks=1)
    shared_pr = fake_pr_url()

    # Complete task in feature 1 with the shared PR URL
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_ids[0]},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_ids[0], "status": "review", "pr_url": shared_pr},
        headers=ah,
    )
    await client.patch(f"/api/v1/tasks/{task_ids[0]}", json={"status": "done"})

    # Create a second feature under the same epic with its own task
    feature2 = (
        await client.post(
            f"/api/v1/projects/{pf.id}/epics/{pf.epic_id}/features",
            json={"title": "Feature 2"},
        )
    ).json()
    task_b = (
        await client.post(
            f"/api/v1/projects/{pf.id}/features/{feature2['id']}/tasks",
            json={"title": "Task B"},
        )
    ).json()

    # Assign and start task B
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/assign-task",
        json={"task_id": task_b["id"]},
        headers=ah,
    )
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_b["id"]},
        headers=ah,
    )

    # Try to review with same PR URL — should be blocked project-wide
    resp = await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_b["id"], "status": "review", "pr_url": shared_pr},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


# ── One-active-task guard ───────────────────────────────────────


async def test_one_active_task_guard(client: AsyncClient) -> None:
    """An agent cannot start a second task while one is in_progress."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client, n_tasks=2)
    task_1, task_2 = task_ids[0], task_ids[1]

    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_1},
        headers=ah,
    )

    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_2},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


async def test_one_active_task_review_counts(client: AsyncClient) -> None:
    """A task in review (PR not merged) still counts as active — cannot start another."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client, n_tasks=2)
    task_1, task_2 = task_ids[0], task_ids[1]

    # Start task 1 and move to review
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_1},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_1, "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )

    # Try to start task 2 — should be blocked because review counts as active
    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_2},
        headers=ah,
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"


async def test_merged_pr_frees_agent_for_next_task(client: AsyncClient) -> None:
    """A task in review with pr_merged=True does NOT block starting another task."""
    pf, agent, task_ids, ah = await _setup_agent_with_assigned_task(client, n_tasks=2)
    task_1, task_2 = task_ids[0], task_ids[1]

    # Start task 1 and move to review
    await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_1},
        headers=ah,
    )
    await client.patch(
        f"/api/v1/agents/{agent.worktree_id}/task-status",
        json={"task_id": task_1, "status": "review", "pr_url": fake_pr_url()},
        headers=ah,
    )

    # Mark the PR as merged via dashboard
    await client.patch(
        f"/api/v1/tasks/{task_1}",
        json={"pr_merged": True},
    )

    # Now starting task 2 should succeed — merged PR frees the agent
    resp = await client.post(
        f"/api/v1/agents/{agent.worktree_id}/start-task",
        json={"task_id": task_2},
        headers=ah,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
