from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.board.models import Epic, Feature, FeatureDependency, Project, Task


async def test_create_project(db_session: AsyncSession):
    project = Project(name="test-project", description="A test project")
    db_session.add(project)
    await db_session.commit()

    result = await db_session.execute(select(Project).where(Project.name == "test-project"))
    row = result.scalar_one()
    assert row.name == "test-project"
    assert row.status == "active"
    assert row.id is not None


async def test_create_full_hierarchy(db_session: AsyncSession):
    project = Project(name="hierarchy-test")
    db_session.add(project)
    await db_session.flush()

    epic = Epic(project_id=project.id, title="Auth Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature = Feature(epic_id=epic.id, title="Login Feature", position=0)
    db_session.add(feature)
    await db_session.flush()

    task = Task(feature_id=feature.id, title="Add login form", position=0)
    db_session.add(task)
    await db_session.commit()

    result = await db_session.execute(select(Task).where(Task.title == "Add login form"))
    row = result.scalar_one()
    assert row.status == "backlog"
    assert row.feature_id == feature.id


async def test_feature_dependency(db_session: AsyncSession):
    project = Project(name="dep-test")
    db_session.add(project)
    await db_session.flush()

    epic = Epic(project_id=project.id, title="Epic", position=0)
    db_session.add(epic)
    await db_session.flush()

    feature_a = Feature(epic_id=epic.id, title="Feature A", position=0)
    feature_b = Feature(epic_id=epic.id, title="Feature B", position=1)
    db_session.add_all([feature_a, feature_b])
    await db_session.flush()

    dep = FeatureDependency(feature_id=feature_b.id, depends_on_id=feature_a.id)
    db_session.add(dep)
    await db_session.commit()

    result = await db_session.execute(
        select(FeatureDependency).where(FeatureDependency.feature_id == feature_b.id)
    )
    row = result.scalar_one()
    assert row.depends_on_id == feature_a.id
