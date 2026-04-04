import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Task
from src.board.repository import BoardRepository
from src.board.schemas import ImportPlan
from src.board.services import BoardService


@pytest.fixture
def service(db_session: AsyncSession) -> BoardService:
    return BoardService(BoardRepository(db_session))


# --- API Key ---


async def test_create_project_with_api_key(service: BoardService):
    project, api_key = await service.create_project("key-test", "", "")
    assert project.name == "key-test"
    assert len(api_key) == 64  # hex-encoded 32 bytes
    assert project.api_key_hash != ""
    assert project.api_key_hash != api_key  # stored hashed, not plain


async def test_verify_api_key(service: BoardService):
    project, api_key = await service.create_project("verify-test", "", "")
    verified = await service.verify_api_key(api_key)
    assert verified is not None
    assert verified.id == project.id


async def test_verify_bad_api_key(service: BoardService):
    await service.create_project("bad-key-test", "", "")
    verified = await service.verify_api_key("not-a-real-key")
    assert verified is None


# --- Status Roll-Up ---


async def test_rollup_feature_all_done(service: BoardService, db_session: AsyncSession):
    project, _ = await service.create_project("rollup-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="done", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="done", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    await db_session.refresh(epic)
    assert feature.status == "done"
    assert epic.status == "done"


async def test_rollup_feature_in_progress(service: BoardService, db_session: AsyncSession):
    project, _ = await service.create_project("rollup-ip-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="in_progress", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="backlog", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    assert feature.status == "in_progress"


async def test_rollup_feature_in_review(service: BoardService, db_session: AsyncSession):
    project, _ = await service.create_project("rollup-review-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="review", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="done", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    assert feature.status == "review"


async def test_rollup_feature_testing_counts_as_in_progress(
    service: BoardService, db_session: AsyncSession
):
    project, _ = await service.create_project("rollup-testing-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="testing", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="done", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    assert feature.status == "in_progress"


# --- Import ---


async def test_import_plan(service: BoardService):
    project, _ = await service.create_project("svc-import-test", "", "")
    plan = ImportPlan(
        epics=[
            {
                "title": "Auth Epic",
                "features": [
                    {
                        "title": "Login",
                        "tasks": [
                            {"title": "Login form"},
                            {"title": "Login API"},
                        ],
                    }
                ],
            }
        ]
    )
    result = await service.import_plan(project.id, plan)
    assert result["epics_created"] == 1
    assert result["features_created"] == 1
    assert result["tasks_created"] == 2
