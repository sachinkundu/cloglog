# T-125: Filtered Board Queries & get_active_tasks MCP Tool

The board endpoint previously returned all tasks (103K+ chars), overwhelming agent context windows. This adds filtering to reduce response size and a new compact endpoint for agent queries.

Create a project with tasks in various statuses, then exercise every new filter and the active-tasks endpoint:

```bash
uv run python3 -c "
import asyncio, json, uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

async def demo():
    from src.gateway.app import create_app
    from src.shared.database import get_session, Base
    import src.board.models, src.agent.models, src.document.models

    db = f'cloglog_demo_{uuid.uuid4().hex[:8]}'
    import asyncpg
    conn = await asyncpg.connect('postgresql://cloglog:cloglog_dev@localhost:5432/cloglog')
    await conn.execute(f'CREATE DATABASE {db}')
    await conn.close()

    url = f'postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/{db}'
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    sf = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()
    async def override():
        async with sf() as s: yield s
    app.dependency_overrides[get_session] = override

    H = {'X-Dashboard-Key': 'cloglog-dashboard-dev'}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', headers=H) as c:
        p = (await c.post('/api/v1/projects', json={'name': 'demo'})).json()
        pid = p['id']
        e1 = (await c.post(f'/api/v1/projects/{pid}/epics', json={'title': 'Auth'})).json()
        e2 = (await c.post(f'/api/v1/projects/{pid}/epics', json={'title': 'Board'})).json()
        f1 = (await c.post(f'/api/v1/projects/{pid}/epics/{e1[\"id\"]}/features', json={'title': 'Login'})).json()
        f2 = (await c.post(f'/api/v1/projects/{pid}/epics/{e2[\"id\"]}/features', json={'title': 'Kanban'})).json()
        t1 = (await c.post(f'/api/v1/projects/{pid}/features/{f1[\"id\"]}/tasks', json={'title': 'T1-backlog'})).json()
        t2 = (await c.post(f'/api/v1/projects/{pid}/features/{f1[\"id\"]}/tasks', json={'title': 'T2-progress'})).json()
        await c.patch(f'/api/v1/tasks/{t2[\"id\"]}', json={'status': 'in_progress'})
        t3 = (await c.post(f'/api/v1/projects/{pid}/features/{f1[\"id\"]}/tasks', json={'title': 'T3-done'})).json()
        await c.patch(f'/api/v1/tasks/{t3[\"id\"]}', json={'status': 'done'})
        t4 = (await c.post(f'/api/v1/projects/{pid}/features/{f2[\"id\"]}/tasks', json={'title': 'T4-review'})).json()
        await c.patch(f'/api/v1/tasks/{t4[\"id\"]}', json={'status': 'review'})

        r = (await c.get(f'/api/v1/projects/{pid}/board')).json()
        print(f'No filters: total_tasks={r[\"total_tasks\"]}, done_count={r[\"done_count\"]}')

        r = (await c.get(f'/api/v1/projects/{pid}/board', params={'exclude_done': 'true'})).json()
        print(f'exclude_done=true: total_tasks={r[\"total_tasks\"]}, done_count={r[\"done_count\"]}')

        r = (await c.get(f'/api/v1/projects/{pid}/board', params={'status': ['in_progress', 'review']})).json()
        print(f'status=in_progress,review: total_tasks={r[\"total_tasks\"]}')

        r = (await c.get(f'/api/v1/projects/{pid}/board', params={'epic_id': e2['id']})).json()
        print(f'epic_id=Board: total_tasks={r[\"total_tasks\"]}')

        r = (await c.get(f'/api/v1/projects/{pid}/active-tasks')).json()
        print(f'active-tasks: count={len(r)}, size={len(json.dumps(r))} chars')
        for t in r:
            print(f'  {t[\"title\"]} [{t[\"status\"]}]')

    await engine.dispose()
    conn = await asyncpg.connect('postgresql://cloglog:cloglog_dev@localhost:5432/cloglog')
    await conn.execute(f'DROP DATABASE {db}')
    await conn.close()

asyncio.run(demo())
"
```

```output
No filters: total_tasks=4, done_count=1
exclude_done=true: total_tasks=3, done_count=0
status=in_progress,review: total_tasks=2
epic_id=Board: total_tasks=1
active-tasks: count=3, size=654 chars
  T1-backlog [backlog]
  T2-progress [in_progress]
  T4-review [review]
```
