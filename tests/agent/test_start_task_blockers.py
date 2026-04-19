"""Integration tests for the F-11 start_task / update_task_status blocker guard."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, FeatureDependency, Task


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _agent_auth(agent_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {agent_token}", "X-Dashboard-Key": ""}


async def _create_project(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": f"blocker-{uuid.uuid4().hex[:8]}", "description": ""},
    )
    assert resp.status_code == 201
    return resp.json()


async def _register_agent(client: AsyncClient, api_key: str, path: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": path, "branch_name": path.split("/")[-1]},
        headers=_auth(api_key),
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["worktree_id"], data["agent_token"]


async def _make_chain(
    db: AsyncSession, project_id: str, feature_title: str = "F"
) -> tuple[Epic, Feature]:
    pid = uuid.UUID(project_id)
    epic = Epic(project_id=pid, title="E", position=0)
    db.add(epic)
    await db.commit()
    await db.refresh(epic)
    feature = Feature(epic_id=epic.id, title=feature_title, position=0)
    db.add(feature)
    await db.commit()
    await db.refresh(feature)
    return epic, feature


async def _make_task(
    db: AsyncSession,
    feature: Feature,
    title: str,
    task_type: str = "task",
    status: str = "backlog",
    pr_url: str | None = None,
    artifact_path: str | None = None,
) -> Task:
    t = Task(
        feature_id=feature.id,
        title=title,
        description="",
        priority="normal",
        position=0,
        status=status,
        task_type=task_type,
        pr_url=pr_url,
        artifact_path=artifact_path,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


class TestFeatureBlockerCrossWorktree:
    """Two worktrees, downstream worktree starts a task whose feature
    depends on an upstream feature."""

    async def test_feature_blocker_emits_structured_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        project = await _create_project(client)
        _, feature_upstream = await _make_chain(db_session, project["id"], "Upstream")
        feature_downstream = Feature(
            epic_id=feature_upstream.epic_id,
            title="Downstream",
            position=1,
        )
        db_session.add(feature_downstream)
        await db_session.commit()
        await db_session.refresh(feature_downstream)

        # Incomplete upstream task
        await _make_task(db_session, feature_upstream, "upstream-t", status="backlog")
        downstream_task = await _make_task(db_session, feature_downstream, "downstream-t")

        # Dependency: downstream depends on upstream
        db_session.add(
            FeatureDependency(feature_id=feature_downstream.id, depends_on_id=feature_upstream.id)
        )
        await db_session.commit()

        wt_id, token = await _register_agent(client, project["api_key"], "/tmp/wt-down")

        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": str(downstream_task.id)},
            headers=_agent_auth(token),
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "task_blocked"
        assert len(detail["blockers"]) == 1
        b = detail["blockers"][0]
        assert b["kind"] == "feature"
        assert b["feature_id"] == str(feature_upstream.id)
        assert b["feature_title"] == "Upstream"

    async def test_resolves_when_upstream_in_review_with_pr_url(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        project = await _create_project(client)
        _, feature_upstream = await _make_chain(db_session, project["id"], "Upstream")
        feature_downstream = Feature(
            epic_id=feature_upstream.epic_id,
            title="Downstream",
            position=1,
        )
        db_session.add(feature_downstream)
        await db_session.commit()
        await db_session.refresh(feature_downstream)

        await _make_task(
            db_session,
            feature_upstream,
            "upstream-t",
            status="review",
            pr_url="https://github.com/x/y/pull/7",
        )
        downstream_task = await _make_task(db_session, feature_downstream, "downstream-t")
        db_session.add(
            FeatureDependency(feature_id=feature_downstream.id, depends_on_id=feature_upstream.id)
        )
        await db_session.commit()

        wt_id, token = await _register_agent(client, project["api_key"], "/tmp/wt-ok")
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": str(downstream_task.id)},
            headers=_agent_auth(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"


class TestUpdateTaskStatusGuard:
    """The same blocker check must fire when moving into in_progress via
    update_task_status — it's a separate endpoint agents could otherwise
    use to bypass start_task."""

    async def test_patch_in_progress_respects_blockers(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        project = await _create_project(client)
        _, feature_upstream = await _make_chain(db_session, project["id"], "Upstream")
        feature_downstream = Feature(
            epic_id=feature_upstream.epic_id,
            title="Downstream",
            position=1,
        )
        db_session.add(feature_downstream)
        await db_session.commit()
        await db_session.refresh(feature_downstream)

        await _make_task(db_session, feature_upstream, "u", status="backlog")
        downstream_task = await _make_task(db_session, feature_downstream, "d")
        db_session.add(
            FeatureDependency(feature_id=feature_downstream.id, depends_on_id=feature_upstream.id)
        )
        await db_session.commit()

        wt_id, token = await _register_agent(client, project["api_key"], "/tmp/wt-patch")
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": str(downstream_task.id), "status": "in_progress"},
            headers=_agent_auth(token),
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "task_blocked"
        assert detail["blockers"][0]["kind"] == "feature"

    async def test_patch_review_still_requires_pr_url(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Pre-existing contract: PATCH status=review without pr_url → 409
        with a plain string detail. The blocker guard must not swallow this."""
        project = await _create_project(client)
        _, feature = await _make_chain(db_session, project["id"])
        task = await _make_task(db_session, feature, "t", task_type="task", status="in_progress")
        wt_id, token = await _register_agent(client, project["api_key"], "/tmp/wt-review")

        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": str(task.id), "status": "review"},
            headers=_agent_auth(token),
        )
        assert resp.status_code == 409
        # Legacy flat-string detail, unchanged
        assert isinstance(resp.json()["detail"], str)
        assert "PR URL" in resp.json()["detail"]


class TestSameWorktreeActiveTaskGuardFiresFirst:
    """When a single worktree holds task T1 and tries to start dependent T2
    on the same worktree, the pre-existing single-active-task guard must
    fire BEFORE the new blocker guard. The blocker-resolver's rule
    (done || review+pr_url) is necessary but not sufficient for same-worktree
    chains — the active-task guard independently requires pr_merged=True."""

    async def test_active_task_guard_message_is_preserved(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        project = await _create_project(client)
        _, feature = await _make_chain(db_session, project["id"])
        t1 = await _make_task(db_session, feature, "t1")
        t2 = await _make_task(db_session, feature, "t2")

        wt_id, token = await _register_agent(client, project["api_key"], "/tmp/wt-same")

        # Start t1, move to review with pr_url (pr_merged still False)
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": str(t1.id)},
            headers=_agent_auth(token),
        )
        assert resp.status_code == 200
        resp = await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={
                "task_id": str(t1.id),
                "status": "review",
                "pr_url": "https://github.com/x/y/pull/1",
            },
            headers=_agent_auth(token),
        )
        assert resp.status_code == 204

        # Now try to start t2 on the same worktree — active-task guard should fire
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/start-task",
            json={"task_id": str(t2.id)},
            headers=_agent_auth(token),
        )
        assert resp.status_code == 409
        # Legacy flat-string detail from the active-task guard — NOT the
        # structured task_blocked payload.
        assert isinstance(resp.json()["detail"], str)
        assert "agent already has active task(s)" in resp.json()["detail"]
