# Artifact Attachment State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce artifact attachment as a state machine step for spec/plan tasks after PR merge, so documents are structurally required (not just instructed) before the pipeline can proceed.

**Architecture:** Add an `artifact_path` field to the Task model. When an agent detects its spec/plan PR has merged, it calls a new `report_artifact` endpoint providing the artifact file path. The backend stores the path on the task and creates a Document record attached to the feature. The `_check_pipeline_predecessors` guard is updated to require `artifact_path` on spec/plan predecessor tasks before downstream tasks can start.

**Tech Stack:** Python/FastAPI (backend), SQLAlchemy (model), Alembic (migration), TypeScript (MCP server), pytest (tests)

---

### Task 1: Add `artifact_path` to Task model and create migration

**Files:**
- Modify: `src/board/models.py:112` (add field after `pr_url`)
- Create: `src/alembic/versions/f5a6b7c8d9e0_add_task_artifact_path.py`

- [ ] **Step 1: Write the failing test**

Add a test in `tests/board/test_models.py` that creates a Task with `artifact_path` set and verifies it persists.

```python
async def test_task_artifact_path(db_session: AsyncSession) -> None:
    """Task model supports artifact_path field."""
    project = Project(name=f"test-{uuid.uuid4().hex[:8]}", description="")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id,
        title="Spec task",
        priority="normal",
        position=0,
        task_type="spec",
        artifact_path="docs/specs/F-1-spec.md",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    assert task.artifact_path == "docs/specs/F-1-spec.md"


async def test_task_artifact_path_default_none(db_session: AsyncSession) -> None:
    """Task artifact_path defaults to None."""
    project = Project(name=f"test-{uuid.uuid4().hex[:8]}", description="")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id,
        title="Impl task",
        priority="normal",
        position=0,
        task_type="impl",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    assert task.artifact_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/board/test_models.py::test_task_artifact_path -v`
Expected: FAIL with `TypeError` — `artifact_path` not a known field on Task.

- [ ] **Step 3: Add the field to the Task model**

In `src/board/models.py`, add after line 112 (`pr_url`):

```python
artifact_path: Mapped[str | None] = mapped_column(String(1000), default=None)
```

- [ ] **Step 4: Create the Alembic migration**

Create `src/alembic/versions/f5a6b7c8d9e0_add_task_artifact_path.py`:

```python
"""add artifact_path to tasks

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-04-09
"""

import sqlalchemy as sa

from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("artifact_path", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "artifact_path")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/board/test_models.py::test_task_artifact_path tests/board/test_models.py::test_task_artifact_path_default_none -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/board/models.py src/alembic/versions/f5a6b7c8d9e0_add_task_artifact_path.py tests/board/test_models.py
git commit -m "feat: add artifact_path field to Task model"
```

---

### Task 2: Update schemas to expose `artifact_path`

**Files:**
- Modify: `src/board/schemas.py:142` (add to `TaskResponse`)
- Modify: `src/board/schemas.py:200` (add to `BacklogTask`)
- Modify: `src/agent/schemas.py:70-78` (add to `TaskInfo`)

- [ ] **Step 1: Write the failing test**

In `tests/board/test_routes.py`, find an existing test that checks `TaskResponse` fields and verify `artifact_path` is included. Or add a targeted assertion to an existing test that creates a task and checks the response contains `artifact_path: null`.

```python
async def test_task_response_includes_artifact_path(client: AsyncClient, db_session: AsyncSession) -> None:
    """Task API response includes artifact_path field."""
    # Create project → epic → feature → task chain via API or DB
    project = Project(name=f"test-{uuid.uuid4().hex[:8]}", description="")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    epic = Epic(project_id=project.id, title="E", position=0, number=1)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0, number=1)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id, title="T", priority="normal", position=0, number=1,
        task_type="spec", artifact_path="docs/specs/F-1.md",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    resp = await client.get(f"/api/v1/projects/{project.id}/board")
    assert resp.status_code == 200
    board = resp.json()
    # Find the task in the board columns
    found = False
    for col in board["columns"]:
        for card in col["tasks"]:
            if card["id"] == str(task.id):
                assert card["artifact_path"] == "docs/specs/F-1.md"
                found = True
    assert found, "Task not found in board response"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/board/test_routes.py::test_task_response_includes_artifact_path -v`
Expected: FAIL — `artifact_path` not in response schema.

- [ ] **Step 3: Add `artifact_path` to schemas**

In `src/board/schemas.py`, add to `TaskResponse` (after `pr_url` on line 142):
```python
artifact_path: str | None = None
```

In `src/board/schemas.py`, add to `BacklogTask` (after `pr_url` on line 200):
```python
artifact_path: str | None = None
```

In `src/agent/schemas.py`, add to `TaskInfo` (after `priority` on line 77):
```python
artifact_path: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/board/test_routes.py::test_task_response_includes_artifact_path -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/board/schemas.py src/agent/schemas.py tests/board/test_routes.py
git commit -m "feat: expose artifact_path in task response schemas"
```

---

### Task 3: Create `report_artifact` agent service method

**Files:**
- Modify: `src/agent/services.py` (add `report_artifact` method after `update_task_status`)

This is the core state machine step. The method:
1. Validates the task is a `spec` or `plan` type (only these produce artifacts)
2. Validates the task is in `review` status (artifact comes after PR merge)
3. Sets `artifact_path` on the task
4. Creates a Document record attached to the **feature** (not the task) via the document context interface
5. Emits an event

- [ ] **Step 1: Write the failing tests**

Add to `tests/agent/test_unit.py`:

```python
async def test_report_artifact_sets_path(db_session: AsyncSession) -> None:
    """report_artifact stores the artifact path on a spec task."""
    project = await _create_project(db_session)
    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id, title="Write spec", priority="normal",
        position=0, status="review", task_type="spec",
        pr_url="https://github.com/test/repo/pull/1",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    reg = await service.register(project.id, "/repo/wt-art", "wt-art")
    wt_id = reg["worktree_id"]
    await BoardRepository(db_session).update_task(task.id, worktree_id=wt_id)

    result = await service.report_artifact(wt_id, task.id, "docs/specs/F-1-spec.md")

    assert result["artifact_path"] == "docs/specs/F-1-spec.md"
    updated = await BoardRepository(db_session).get_task(task.id)
    assert updated is not None
    assert updated.artifact_path == "docs/specs/F-1-spec.md"


async def test_report_artifact_rejects_non_spec_plan(db_session: AsyncSession) -> None:
    """report_artifact rejects impl and task types."""
    project = await _create_project(db_session)
    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id, title="Implement", priority="normal",
        position=0, status="review", task_type="impl",
        pr_url="https://github.com/test/repo/pull/2",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    reg = await service.register(project.id, "/repo/wt-art2", "wt-art2")
    wt_id = reg["worktree_id"]
    await BoardRepository(db_session).update_task(task.id, worktree_id=wt_id)

    with pytest.raises(ValueError, match="only spec and plan tasks produce artifacts"):
        await service.report_artifact(wt_id, task.id, "docs/impl.md")


async def test_report_artifact_rejects_non_review_status(db_session: AsyncSession) -> None:
    """report_artifact rejects tasks not in review status."""
    project = await _create_project(db_session)
    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id, title="Write spec", priority="normal",
        position=0, status="in_progress", task_type="spec",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    reg = await service.register(project.id, "/repo/wt-art3", "wt-art3")
    wt_id = reg["worktree_id"]
    await BoardRepository(db_session).update_task(task.id, worktree_id=wt_id)

    with pytest.raises(ValueError, match="must be in 'review' status"):
        await service.report_artifact(wt_id, task.id, "docs/specs/F-1-spec.md")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_unit.py::TestAgentService::test_report_artifact_sets_path tests/agent/test_unit.py::TestAgentService::test_report_artifact_rejects_non_spec_plan tests/agent/test_unit.py::TestAgentService::test_report_artifact_rejects_non_review_status -v`
Expected: FAIL — `report_artifact` method doesn't exist.

Note: If these tests are module-level functions (not in a class), adjust the test path accordingly. Place them inside `TestAgentService` class for consistency with existing tests.

- [ ] **Step 3: Implement `report_artifact` method**

Add to `src/agent/services.py` after `update_task_status` (after line 349):

```python
async def report_artifact(
    self, worktree_id: UUID, task_id: UUID, artifact_path: str
) -> dict[str, object]:
    """Record the artifact path for a spec or plan task after its PR merges.

    This is a state machine step: only spec/plan tasks produce artifacts,
    and the task must be in review status (PR has been merged).
    """
    worktree = await self._repo.get_worktree(worktree_id)
    if worktree is None:
        raise ValueError(f"Worktree {worktree_id} not found")

    task = await self._board_repo.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    # Guard: only spec and plan tasks produce artifacts
    if task.task_type not in ("spec", "plan"):
        raise ValueError(
            f"Cannot report artifact for {task.task_type} task: "
            f"only spec and plan tasks produce artifacts."
        )

    # Guard: task must be in review (PR merged, agent detected it)
    if task.status != "review":
        raise ValueError(
            f"Cannot report artifact: task must be in 'review' status "
            f"(current: {task.status})."
        )

    # Store artifact path on task
    await self._board_repo.update_task(task_id, artifact_path=artifact_path)

    await event_bus.publish(
        Event(
            type=EventType.TASK_STATUS_CHANGED,
            project_id=worktree.project_id,
            data={
                "task_id": str(task_id),
                "worktree_id": str(worktree_id),
                "action": "artifact_attached",
                "artifact_path": artifact_path,
            },
        )
    )

    return {
        "task_id": task_id,
        "artifact_path": artifact_path,
        "feature_id": task.feature_id,
    }
```

- [ ] **Step 4: Add missing imports if needed**

The method uses `Event`, `EventType`, `event_bus` — all already imported in `services.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_unit.py -k "report_artifact" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent/services.py tests/agent/test_unit.py
git commit -m "feat: add report_artifact state machine step for spec/plan tasks"
```

---

### Task 4: Strengthen pipeline guard to require artifact on spec/plan predecessors

**Files:**
- Modify: `src/agent/services.py:135-167` (update `_check_pipeline_predecessors`)

The `is_completed` check currently accepts `status == "done"` or `status == "review" and pr_url`. For spec/plan predecessors, also require `artifact_path` to be set.

- [ ] **Step 1: Write the failing tests**

Add to `tests/agent/test_unit.py` inside `TestAgentService`:

```python
async def test_pipeline_blocks_plan_when_spec_has_no_artifact(self, db_session: AsyncSession) -> None:
    """Cannot start plan task if spec predecessor has no artifact_path."""
    project = await _create_project(db_session)
    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    spec_task = Task(
        feature_id=feature.id, title="Spec", priority="normal",
        position=0, status="review", task_type="spec",
        pr_url="https://github.com/test/repo/pull/1",
        # No artifact_path — this should block plan from starting
    )
    plan_task = Task(
        feature_id=feature.id, title="Plan", priority="normal",
        position=1, status="backlog", task_type="plan",
    )
    db_session.add_all([spec_task, plan_task])
    await db_session.commit()
    for t in (spec_task, plan_task):
        await db_session.refresh(t)

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    reg = await service.register(project.id, "/repo/wt-pipe-art", "wt-pipe-art")
    wt_id = reg["worktree_id"]
    await BoardRepository(db_session).update_task(plan_task.id, worktree_id=wt_id)

    with pytest.raises(ValueError, match="artifact not attached"):
        await service.start_task(wt_id, plan_task.id)


async def test_pipeline_allows_plan_when_spec_has_artifact(self, db_session: AsyncSession) -> None:
    """Can start plan task when spec predecessor has artifact_path set."""
    project = await _create_project(db_session)
    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    spec_task = Task(
        feature_id=feature.id, title="Spec", priority="normal",
        position=0, status="review", task_type="spec",
        pr_url="https://github.com/test/repo/pull/1",
        artifact_path="docs/specs/F-1-spec.md",
    )
    plan_task = Task(
        feature_id=feature.id, title="Plan", priority="normal",
        position=1, status="backlog", task_type="plan",
    )
    db_session.add_all([spec_task, plan_task])
    await db_session.commit()
    for t in (spec_task, plan_task):
        await db_session.refresh(t)

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    reg = await service.register(project.id, "/repo/wt-pipe-art2", "wt-pipe-art2")
    wt_id = reg["worktree_id"]
    await BoardRepository(db_session).update_task(plan_task.id, worktree_id=wt_id)

    result = await service.start_task(wt_id, plan_task.id)
    assert result["status"] == "in_progress"


async def test_pipeline_allows_done_spec_without_artifact(self, db_session: AsyncSession) -> None:
    """Spec tasks in done status pass the guard even without artifact (user manually marked done)."""
    project = await _create_project(db_session)
    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    spec_task = Task(
        feature_id=feature.id, title="Spec", priority="normal",
        position=0, status="done", task_type="spec",
        pr_url="https://github.com/test/repo/pull/1",
        # No artifact_path, but status is done — user override
    )
    plan_task = Task(
        feature_id=feature.id, title="Plan", priority="normal",
        position=1, status="backlog", task_type="plan",
    )
    db_session.add_all([spec_task, plan_task])
    await db_session.commit()
    for t in (spec_task, plan_task):
        await db_session.refresh(t)

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    reg = await service.register(project.id, "/repo/wt-pipe-art3", "wt-pipe-art3")
    wt_id = reg["worktree_id"]
    await BoardRepository(db_session).update_task(plan_task.id, worktree_id=wt_id)

    # Should succeed — done status is the human override that bypasses artifact check
    result = await service.start_task(wt_id, plan_task.id)
    assert result["status"] == "in_progress"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_unit.py -k "pipeline_blocks_plan_when_spec_has_no_artifact or pipeline_allows_plan_when_spec_has_artifact or pipeline_allows_done_spec_without_artifact" -v`
Expected: First test FAILS (no artifact check exists). Second and third may pass or fail depending on existing guard behavior.

- [ ] **Step 3: Update `_check_pipeline_predecessors` guard**

In `src/agent/services.py`, update the `is_completed` function inside `_check_pipeline_predecessors`:

```python
def _check_pipeline_predecessors(self, task: Task, feature_tasks: list[Task]) -> None:
    """Check that predecessor task types in the pipeline are done."""
    if task.task_type == "task":
        return  # Standalone tasks have no pipeline deps

    predecessor_type: str | None = None
    if task.task_type == "plan":
        predecessor_type = "spec"
    elif task.task_type == "impl":
        predecessor_type = "plan"

    if predecessor_type is None:
        return

    predecessors = [t for t in feature_tasks if t.task_type == predecessor_type]
    if not predecessors:
        return  # No predecessor tasks exist — allow start

    # Accept "done" or "review with a pr_url" as completed — agents shouldn't
    # be blocked waiting for the user to drag a card to done on the board
    # when the PR is already merged.
    def is_completed(t: Task) -> bool:
        if t.status == "done":
            return True
        if t.status == "review" and bool(t.pr_url):
            # For spec/plan predecessors, also require artifact attachment
            if t.task_type in ("spec", "plan") and not t.artifact_path:
                return False
            return True
        return False

    undone = [t for t in predecessors if not is_completed(t)]
    if undone:
        # Check if the issue is missing artifact vs not done at all
        missing_artifact = [
            t for t in undone
            if t.status == "review" and bool(t.pr_url) and not t.artifact_path
        ]
        if missing_artifact:
            titles = ", ".join(f"T-{t.number}" for t in missing_artifact)
            raise ValueError(
                f"Cannot start {task.task_type} task: "
                f"{predecessor_type} task(s) {titles} in review but "
                f"artifact not attached. "
                f"Call report_artifact first."
            )
        titles = ", ".join(f"T-{t.number} ({t.status})" for t in undone)
        raise ValueError(
            f"Cannot start {task.task_type} task: "
            f"{predecessor_type} task(s) not done yet: "
            f"{titles}. "
            f"Wait for the {predecessor_type} PR to be merged."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_unit.py -k "pipeline" -v`
Expected: All pipeline tests PASS (both new and existing).

- [ ] **Step 5: Commit**

```bash
git add src/agent/services.py tests/agent/test_unit.py
git commit -m "feat: pipeline guard requires artifact on spec/plan predecessors"
```

---

### Task 5: Add `report_artifact` API endpoint

**Files:**
- Modify: `src/agent/schemas.py` (add `ReportArtifactRequest` schema)
- Modify: `src/agent/routes.py` (add endpoint)

- [ ] **Step 1: Write the failing test**

Add to `tests/agent/test_integration.py`:

```python
class TestReportArtifactAPI:
    async def test_report_artifact_success(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Agent can report artifact for a spec task in review."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        pid = uuid.UUID(project["id"])

        epic = Epic(project_id=pid, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        task = Task(
            feature_id=feature.id, title="Write spec", priority="normal",
            position=0, status="assigned", task_type="spec",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": f"/repo/wt-art-{uuid.uuid4().hex[:6]}", "branch_name": "wt-art"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]

        # Start task and move to review
        await client.post(f"/api/v1/agents/{wt_id}/start-task", json={"task_id": str(task.id)})
        await client.patch(
            f"/api/v1/agents/{wt_id}/task-status",
            json={"task_id": str(task.id), "status": "review", "pr_url": "https://github.com/test/pull/1"},
        )

        # Report artifact
        resp = await client.post(
            f"/api/v1/agents/{wt_id}/report-artifact",
            json={"task_id": str(task.id), "artifact_path": "docs/specs/F-1-spec.md"},
        )
        assert resp.status_code == 200
        assert resp.json()["artifact_path"] == "docs/specs/F-1-spec.md"

        # Verify task updated in DB
        updated = await BoardRepository(db_session).get_task(task.id)
        assert updated is not None
        assert updated.artifact_path == "docs/specs/F-1-spec.md"

    async def test_report_artifact_rejects_impl_task(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Cannot report artifact for impl task — returns 409."""
        project = await _create_project_via_api(client)
        h = _auth(project["api_key"])
        pid = uuid.UUID(project["id"])

        epic = Epic(project_id=pid, title="E", position=0)
        db_session.add(epic)
        await db_session.commit()
        await db_session.refresh(epic)

        feature = Feature(epic_id=epic.id, title="F", position=0)
        db_session.add(feature)
        await db_session.commit()
        await db_session.refresh(feature)

        task = Task(
            feature_id=feature.id, title="Implement", priority="normal",
            position=0, status="review", task_type="impl",
            pr_url="https://github.com/test/pull/2",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        reg = await client.post(
            "/api/v1/agents/register",
            json={"worktree_path": f"/repo/wt-art-impl-{uuid.uuid4().hex[:6]}", "branch_name": "wt-art-impl"},
            headers=h,
        )
        wt_id = reg.json()["worktree_id"]
        await BoardRepository(db_session).update_task(task.id, worktree_id=uuid.UUID(wt_id))

        resp = await client.post(
            f"/api/v1/agents/{wt_id}/report-artifact",
            json={"task_id": str(task.id), "artifact_path": "docs/impl.md"},
        )
        assert resp.status_code == 409
        assert "only spec and plan" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_integration.py::TestReportArtifactAPI -v`
Expected: FAIL — 404 (endpoint doesn't exist).

- [ ] **Step 3: Add the request schema**

In `src/agent/schemas.py`, add after `AddTaskNoteRequest`:

```python
class ReportArtifactRequest(BaseModel):
    task_id: UUID
    artifact_path: str
```

- [ ] **Step 4: Add the route**

In `src/agent/routes.py`, add the import of `ReportArtifactRequest` to the import block and add the endpoint:

```python
@router.post("/agents/{worktree_id}/report-artifact", status_code=200)
async def report_artifact(
    worktree_id: UUID, body: ReportArtifactRequest, service: ServiceDep
) -> dict[str, object]:
    """Report the artifact path for a spec/plan task after its PR merges."""
    try:
        return await service.report_artifact(worktree_id, body.task_id, body.artifact_path)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/agent/test_integration.py::TestReportArtifactAPI -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent/schemas.py src/agent/routes.py tests/agent/test_integration.py
git commit -m "feat: add report-artifact agent endpoint"
```

---

### Task 6: Add `report_artifact` MCP tool

**Files:**
- Modify: `mcp-server/src/tools.ts` (add handler interface + implementation)
- Modify: `mcp-server/src/server.ts` (register tool)

- [ ] **Step 1: Add to tool handler interface**

In `mcp-server/src/tools.ts`, add to the `ToolHandlers` interface:

```typescript
report_artifact(args: { worktree_id: string; task_id: string; artifact_path: string }): Promise<unknown>
```

- [ ] **Step 2: Add handler implementation**

In `mcp-server/src/tools.ts`, add to `createToolHandlers` return object:

```typescript
async report_artifact({ worktree_id, task_id, artifact_path }) {
  return client.request('POST', `/api/v1/agents/${worktree_id}/report-artifact`, {
    task_id,
    artifact_path,
  })
},
```

- [ ] **Step 3: Register the tool in server.ts**

In `mcp-server/src/server.ts`, add the tool registration (find the section near `attach_document` registration):

```typescript
server.tool(
  'report_artifact',
  'Report the artifact path for a spec or plan task after its PR merges. This is a required state machine step — the pipeline will block downstream tasks until the artifact is attached.',
  {
    worktree_id: z.string().describe('UUID of the worktree'),
    task_id: z.string().describe('UUID of the spec or plan task'),
    artifact_path: z.string().describe('Repo-relative path to the artifact file (e.g. docs/specs/F-1-spec.md)'),
  },
  async ({ worktree_id, task_id, artifact_path }) => {
    requireRegistered()
    const result = await handlers.report_artifact({ worktree_id, task_id, artifact_path })
    return { content: [{ type: 'text' as const, text: `Artifact reported for task ${task_id}: ${artifact_path}` }] }
  }
)
```

- [ ] **Step 4: Build the MCP server**

Run: `cd mcp-server && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 5: Run MCP server tests**

Run: `cd mcp-server && npm test`
Expected: Existing tests pass. (New tool will be exercised via integration testing.)

- [ ] **Step 6: Commit**

```bash
git add mcp-server/src/tools.ts mcp-server/src/server.ts
git commit -m "feat: add report_artifact MCP tool"
```

---

### Task 7: Update `report_artifact` to also create a Document record

**Files:**
- Modify: `src/agent/services.py` (inject document creation into `report_artifact`)
- Modify: `src/agent/routes.py` (pass document repo to service)

The `report_artifact` method should also create a Document record attached to the feature (not the task), so the artifact content is stored in the document context and visible on the feature card.

- [ ] **Step 1: Write the failing test**

Add to `tests/agent/test_unit.py`:

```python
async def test_report_artifact_creates_document(db_session: AsyncSession) -> None:
    """report_artifact creates a Document attached to the feature."""
    from src.document.repository import DocumentRepository

    project = await _create_project(db_session)
    epic = Epic(project_id=project.id, title="E", position=0)
    db_session.add(epic)
    await db_session.commit()
    await db_session.refresh(epic)

    feature = Feature(epic_id=epic.id, title="F", position=0)
    db_session.add(feature)
    await db_session.commit()
    await db_session.refresh(feature)

    task = Task(
        feature_id=feature.id, title="Write spec", priority="normal",
        position=0, status="review", task_type="spec",
        pr_url="https://github.com/test/repo/pull/1",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    service = AgentService(AgentRepository(db_session), BoardRepository(db_session))
    reg = await service.register(project.id, "/repo/wt-art-doc", "wt-art-doc")
    wt_id = reg["worktree_id"]
    await BoardRepository(db_session).update_task(task.id, worktree_id=wt_id)

    await service.report_artifact(wt_id, task.id, "docs/specs/F-1-spec.md")

    # Check document was created attached to the feature
    doc_repo = DocumentRepository(db_session)
    docs = await doc_repo.get_documents_for_entity("feature", feature.id)
    assert len(docs) == 1
    assert docs[0].source_path == "docs/specs/F-1-spec.md"
    assert docs[0].doc_type == "spec"
    assert docs[0].attached_to_id == feature.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_unit.py -k "report_artifact_creates_document" -v`
Expected: FAIL — no document created.

- [ ] **Step 3: Update `report_artifact` to create a Document**

In `src/agent/services.py`, add `DocumentRepository` import and update the method:

```python
from src.document.repository import DocumentRepository
```

Update `report_artifact` to accept and use a `DocumentRepository`:

```python
async def report_artifact(
    self, worktree_id: UUID, task_id: UUID, artifact_path: str
) -> dict[str, object]:
    """Record the artifact path for a spec or plan task after its PR merges."""
    worktree = await self._repo.get_worktree(worktree_id)
    if worktree is None:
        raise ValueError(f"Worktree {worktree_id} not found")

    task = await self._board_repo.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if task.task_type not in ("spec", "plan"):
        raise ValueError(
            f"Cannot report artifact for {task.task_type} task: "
            f"only spec and plan tasks produce artifacts."
        )

    if task.status != "review":
        raise ValueError(
            f"Cannot report artifact: task must be in 'review' status "
            f"(current: {task.status})."
        )

    # Store artifact path on task
    await self._board_repo.update_task(task_id, artifact_path=artifact_path)

    # Create a Document attached to the feature
    doc_repo = DocumentRepository(self._board_repo._session)
    await doc_repo.create_document(
        title=f"{task.task_type} — {task.title}",
        content="",  # Content lives in the repo file, not duplicated here
        doc_type=task.task_type,
        source_path=artifact_path,
        attached_to_type="feature",
        attached_to_id=task.feature_id,
    )

    await event_bus.publish(
        Event(
            type=EventType.TASK_STATUS_CHANGED,
            project_id=worktree.project_id,
            data={
                "task_id": str(task_id),
                "worktree_id": str(worktree_id),
                "action": "artifact_attached",
                "artifact_path": artifact_path,
            },
        )
    )

    return {
        "task_id": task_id,
        "artifact_path": artifact_path,
        "feature_id": task.feature_id,
    }
```

Note: We use `self._board_repo._session` to get the shared session for DocumentRepository. This avoids needing a constructor change — both repos share the same DB session in the request lifecycle.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_unit.py -k "report_artifact" -v`
Expected: All report_artifact tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/services.py tests/agent/test_unit.py
git commit -m "feat: report_artifact creates Document record on feature"
```

---

### Task 8: Run full quality gate and fix any issues

**Files:** Any files that need fixes from quality gate output.

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 2: Run linter**

Run: `make lint`
Expected: No errors.

- [ ] **Step 3: Run type checker**

Run: `make typecheck`
Expected: No errors.

- [ ] **Step 4: Run contract check**

Run: `make contract-check`
Expected: Pass (or update contract if needed).

- [ ] **Step 5: Run full quality gate**

Run: `make quality`
Expected: All checks pass.

- [ ] **Step 6: Fix any failures**

Address any issues found. Common things to check:
- Missing imports
- Type annotation issues (mypy)
- Ruff linting (unused imports, `raise ... from None` in except blocks)
- Contract drift (if report-artifact endpoint needs to be in the contract)

- [ ] **Step 7: Final commit if fixes were needed**

```bash
git add -A
git commit -m "fix: quality gate fixes for artifact attachment feature"
```

---

### Task 9: Update CLAUDE.md with artifact reporting instructions

**Files:**
- Modify: `CLAUDE.md` (update the agent lifecycle sections)

- [ ] **Step 1: Update the PR merge detection flow**

Replace the existing "When merged" line in the PR polling section with:

```markdown
When merged: (1) call `report_artifact` with the artifact file path (spec/plan tasks only), (2) wait for user to move task to done on the board, (3) pick up next task. The pipeline guard enforces artifact attachment — downstream tasks cannot start without it.
```

- [ ] **Step 2: Update the Worktree Hygiene section**

Replace the `attach_document` bullet with:

```markdown
- **Report artifacts after PR merge:** When a spec or plan PR is merged, call `report_artifact` MCP tool with the path to the document file (e.g. `docs/specs/F-1-spec.md`). This is enforced by the state machine — the pipeline guard will block downstream tasks (plan/impl) until the artifact is attached. The tool also creates a Document record on the feature card automatically.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with report_artifact workflow"
```
