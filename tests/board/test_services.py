import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, Task
from src.board.repository import BoardRepository
from src.board.schemas import ImportPlan
from src.board.services import BoardService
from src.document.models import Document


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


async def test_rollup_feature_partial_done_is_in_progress(
    service: BoardService, db_session: AsyncSession
):
    project, _ = await service.create_project("rollup-partial-done-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    t1 = Task(feature_id=feature.id, title="T1", status="in_progress", position=0)
    t2 = Task(feature_id=feature.id, title="T2", status="done", position=1)
    db_session.add_all([t1, t2])
    await db_session.commit()

    await service.recompute_rollup(feature.id)
    await db_session.refresh(feature)
    assert feature.status == "in_progress"


# --- Auto-Attach Document ---


async def test_auto_attach_spec_on_review(service: BoardService, db_session: AsyncSession):
    """Spec task moving to review creates a document attached to the parent feature."""
    project, _ = await service.create_project("attach-spec-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    task = Task(
        feature_id=feature.id,
        title="Write spec",
        status="in_progress",
        task_type="spec",
        position=0,
    )
    db_session.add(task)
    await db_session.commit()

    pr_url = "https://github.com/org/repo/pull/42"
    doc = await service.auto_attach_document_on_review(task, pr_url)

    assert doc is not None
    assert doc.doc_type == "design_spec"
    assert doc.source_path == pr_url
    assert doc.attached_to_type == "feature"
    assert doc.attached_to_id == feature.id
    assert "Spec" in doc.title


async def test_auto_attach_plan_on_review(service: BoardService, db_session: AsyncSession):
    """Plan task moving to review creates an implementation_plan document."""
    project, _ = await service.create_project("attach-plan-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    task = Task(
        feature_id=feature.id,
        title="Write plan",
        status="in_progress",
        task_type="plan",
        position=0,
    )
    db_session.add(task)
    await db_session.commit()

    pr_url = "https://github.com/org/repo/pull/43"
    doc = await service.auto_attach_document_on_review(task, pr_url)

    assert doc is not None
    assert doc.doc_type == "implementation_plan"
    assert doc.source_path == pr_url


async def test_auto_attach_skips_impl_tasks(service: BoardService, db_session: AsyncSession):
    """Impl tasks should NOT auto-attach documents."""
    project, _ = await service.create_project("attach-impl-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    task = Task(
        feature_id=feature.id,
        title="Implement",
        status="in_progress",
        task_type="impl",
        position=0,
    )
    db_session.add(task)
    await db_session.commit()

    doc = await service.auto_attach_document_on_review(task, "https://github.com/org/repo/pull/44")
    assert doc is None


async def test_auto_attach_deduplicates(service: BoardService, db_session: AsyncSession):
    """Same pr_url for same feature should not create duplicate documents."""
    project, _ = await service.create_project("attach-dedup-test", "", "")
    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    task = Task(
        feature_id=feature.id,
        title="Write spec",
        status="in_progress",
        task_type="spec",
        position=0,
    )
    db_session.add(task)
    await db_session.commit()

    pr_url = "https://github.com/org/repo/pull/45"
    doc1 = await service.auto_attach_document_on_review(task, pr_url)
    doc2 = await service.auto_attach_document_on_review(task, pr_url)

    assert doc1 is not None
    assert doc2 is None  # Duplicate was skipped

    # Verify only one document exists
    result = await db_session.execute(
        select(Document).where(
            Document.attached_to_id == feature.id,
            Document.source_path == pr_url,
        )
    )
    docs = list(result.scalars().all())
    assert len(docs) == 1


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
