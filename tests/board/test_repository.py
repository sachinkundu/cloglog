import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Project
from src.board.repository import BoardRepository


@pytest.fixture
def repo(db_session: AsyncSession) -> BoardRepository:
    return BoardRepository(db_session)


@pytest.fixture
async def sample_project(db_session: AsyncSession) -> Project:
    project = Project(name=f"repo-test-{uuid.uuid4().hex[:8]}")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


# --- Project ---


async def test_create_project(repo: BoardRepository):
    project = await repo.create_project("new-project", "desc", "")
    assert project.name == "new-project"
    assert project.id is not None


async def test_get_project(repo: BoardRepository, sample_project: Project):
    project = await repo.get_project(sample_project.id)
    assert project is not None
    assert project.name == sample_project.name


async def test_list_projects(repo: BoardRepository, sample_project: Project):
    projects = await repo.list_projects()
    assert len(projects) >= 1
    assert any(p.id == sample_project.id for p in projects)


# --- Epic ---


async def test_create_epic(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Test Epic", "", "", "", 0)
    assert epic.title == "Test Epic"
    assert epic.project_id == sample_project.id


async def test_list_epics(repo: BoardRepository, sample_project: Project):
    await repo.create_epic(sample_project.id, "Epic 1", "", "", "", 0)
    await repo.create_epic(sample_project.id, "Epic 2", "", "", "", 1)
    epics = await repo.list_epics(sample_project.id)
    assert len(epics) == 2


# --- Feature ---


async def test_create_feature(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Test Feature", "", 0)
    assert feature.title == "Test Feature"


# --- Task ---


async def test_create_task(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    task = await repo.create_task(feature.id, "Test Task", "", "normal", 0)
    assert task.title == "Test Task"
    assert task.status == "backlog"


async def test_update_task(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    task = await repo.create_task(feature.id, "Task", "", "normal", 0)
    updated = await repo.update_task(task.id, status="in_progress")
    assert updated is not None
    assert updated.status == "in_progress"


async def test_delete_task(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    task = await repo.create_task(feature.id, "Task", "", "normal", 0)
    deleted = await repo.delete_task(task.id)
    assert deleted is True
    assert await repo.get_task(task.id) is None


# --- Board query ---


async def test_get_board_tasks(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    await repo.create_task(feature.id, "Task 1", "", "normal", 0)
    await repo.create_task(feature.id, "Task 2", "", "normal", 1)
    tasks = await repo.get_board_tasks(sample_project.id)
    assert len(tasks) == 2


# --- Reorder ---


async def test_reorder_epics(repo: BoardRepository, sample_project: Project):
    e1 = await repo.create_epic(sample_project.id, "Epic 1", "", "", "", 0)
    e2 = await repo.create_epic(sample_project.id, "Epic 2", "", "", "", 1)
    e3 = await repo.create_epic(sample_project.id, "Epic 3", "", "", "", 2)
    # Reverse the order
    await repo.reorder_epics(sample_project.id, [(e3.id, 0), (e2.id, 1), (e1.id, 2)])
    epics = await repo.list_epics(sample_project.id)
    assert epics[0].id == e3.id
    assert epics[1].id == e2.id
    assert epics[2].id == e1.id


async def test_reorder_features(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    f1 = await repo.create_feature(epic.id, "Feature 1", "", 0)
    f2 = await repo.create_feature(epic.id, "Feature 2", "", 1)
    # Swap order
    await repo.reorder_features(epic.id, [(f2.id, 0), (f1.id, 1)])
    features = await repo.list_features(epic.id)
    assert features[0].id == f2.id
    assert features[1].id == f1.id


async def test_reorder_tasks(repo: BoardRepository, sample_project: Project):
    epic = await repo.create_epic(sample_project.id, "Epic", "", "", "", 0)
    feature = await repo.create_feature(epic.id, "Feature", "", 0)
    t1 = await repo.create_task(feature.id, "Task 1", "", "normal", 0)
    t2 = await repo.create_task(feature.id, "Task 2", "", "normal", 1)
    t3 = await repo.create_task(feature.id, "Task 3", "", "normal", 2)
    # Reverse the order
    await repo.reorder_tasks(feature.id, [(t3.id, 0), (t2.id, 1), (t1.id, 2)])
    tasks = await repo.get_tasks_for_feature(feature.id)
    assert tasks[0].id == t3.id
    assert tasks[1].id == t2.id
    assert tasks[2].id == t1.id


async def test_reorder_epics_invalid_id(repo: BoardRepository, sample_project: Project):
    await repo.create_epic(sample_project.id, "Epic 1", "", "", "", 0)
    fake_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Epic IDs not found"):
        await repo.reorder_epics(sample_project.id, [(fake_id, 0)])
