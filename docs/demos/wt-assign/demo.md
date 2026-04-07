# T-32: cloglog agents list CLI command

*2026-04-07T16:31:26Z by Showboat 0.6.1*
<!-- showboat-id: ca99506f-7347-4473-9d58-4641dad1d62a -->

Added `cloglog agents list` CLI command. Lists registered agents for a project showing name, status, branch, current task, and last heartbeat. Supports `--json` output, `--status` filtering, and `--api-key` for authentication.

## List agents (table format)

```bash
uv run python -c "
import respx
from httpx import Response
from typer.testing import CliRunner
from src.gateway.cli import app

PROJECTS = [{\"id\": \"aaa-bbb\", \"name\": \"my-project\", \"status\": \"active\"}]
WORKTREES = [
    {\"id\": \"w1w1w1w1\", \"project_id\": \"aaa-bbb\", \"name\": \"wt-board\",
     \"worktree_path\": \"/code/cloglog/.claude/worktrees/wt-board\",
     \"branch_name\": \"wt-board\", \"status\": \"active\",
     \"current_task_id\": \"t1t1t1t1\", \"last_heartbeat\": \"2026-04-07T12:30:00Z\",
     \"created_at\": \"2026-04-07T10:00:00Z\"},
    {\"id\": \"w2w2w2w2\", \"project_id\": \"aaa-bbb\", \"name\": \"wt-gateway\",
     \"worktree_path\": \"/code/cloglog/.claude/worktrees/wt-gateway\",
     \"branch_name\": \"wt-gateway\", \"status\": \"offline\",
     \"current_task_id\": None, \"last_heartbeat\": \"2026-04-06T09:15:00Z\",
     \"created_at\": \"2026-04-06T08:00:00Z\"}
]

with respx.mock:
    respx.get(\"http://localhost:8000/api/v1/projects\").mock(return_value=Response(200, json=PROJECTS))
    respx.get(\"http://localhost:8000/api/v1/projects/aaa-bbb/worktrees\").mock(return_value=Response(200, json=WORKTREES))
    r = CliRunner().invoke(app, [\"agents\", \"list\", \"--project\", \"my-project\"])
    print(r.output)
"
```

```output

Agents for 'my-project' (2)

  ● wt-board             w1w1w1w1  active     wt-board
    task: t1t1t1t1  heartbeat: 2026-04-07T12:30:00
  ○ wt-gateway           w2w2w2w2  offline    wt-gateway
    task: none  heartbeat: 2026-04-06T09:15:00

```

## List agents (JSON format)

```bash
uv run python -c "
import respx
from httpx import Response
from typer.testing import CliRunner
from src.gateway.cli import app

PROJECTS = [{\"id\": \"aaa-bbb\", \"name\": \"my-project\", \"status\": \"active\"}]
WORKTREES = [
    {\"id\": \"w1w1w1w1\", \"project_id\": \"aaa-bbb\", \"name\": \"wt-board\",
     \"worktree_path\": \"/code/cloglog/.claude/worktrees/wt-board\",
     \"branch_name\": \"wt-board\", \"status\": \"active\",
     \"current_task_id\": \"t1t1t1t1\", \"last_heartbeat\": \"2026-04-07T12:30:00Z\",
     \"created_at\": \"2026-04-07T10:00:00Z\"},
    {\"id\": \"w2w2w2w2\", \"project_id\": \"aaa-bbb\", \"name\": \"wt-gateway\",
     \"worktree_path\": \"/code/cloglog/.claude/worktrees/wt-gateway\",
     \"branch_name\": \"wt-gateway\", \"status\": \"offline\",
     \"current_task_id\": None, \"last_heartbeat\": \"2026-04-06T09:15:00Z\",
     \"created_at\": \"2026-04-06T08:00:00Z\"}
]

with respx.mock:
    respx.get(\"http://localhost:8000/api/v1/projects\").mock(return_value=Response(200, json=PROJECTS))
    respx.get(\"http://localhost:8000/api/v1/projects/aaa-bbb/worktrees\").mock(return_value=Response(200, json=WORKTREES))
    r = CliRunner().invoke(app, [\"agents\", \"list\", \"--project\", \"my-project\", \"--json\"])
    print(r.output)
"
```

```output
[
  {
    "id": "w1w1w1w1",
    "project_id": "aaa-bbb",
    "name": "wt-board",
    "worktree_path": "/code/cloglog/.claude/worktrees/wt-board",
    "branch_name": "wt-board",
    "status": "active",
    "current_task_id": "t1t1t1t1",
    "last_heartbeat": "2026-04-07T12:30:00Z",
    "created_at": "2026-04-07T10:00:00Z"
  },
  {
    "id": "w2w2w2w2",
    "project_id": "aaa-bbb",
    "name": "wt-gateway",
    "worktree_path": "/code/cloglog/.claude/worktrees/wt-gateway",
    "branch_name": "wt-gateway",
    "status": "offline",
    "current_task_id": null,
    "last_heartbeat": "2026-04-06T09:15:00Z",
    "created_at": "2026-04-06T08:00:00Z"
  }
]

```

## Filter by status

```bash
uv run python -c "
import respx
from httpx import Response
from typer.testing import CliRunner
from src.gateway.cli import app

PROJECTS = [{\"id\": \"aaa-bbb\", \"name\": \"my-project\", \"status\": \"active\"}]
WORKTREES = [
    {\"id\": \"w1w1w1w1\", \"project_id\": \"aaa-bbb\", \"name\": \"wt-board\",
     \"worktree_path\": \"/code/cloglog/.claude/worktrees/wt-board\",
     \"branch_name\": \"wt-board\", \"status\": \"active\",
     \"current_task_id\": \"t1t1t1t1\", \"last_heartbeat\": \"2026-04-07T12:30:00Z\",
     \"created_at\": \"2026-04-07T10:00:00Z\"},
    {\"id\": \"w2w2w2w2\", \"project_id\": \"aaa-bbb\", \"name\": \"wt-gateway\",
     \"worktree_path\": \"/code/cloglog/.claude/worktrees/wt-gateway\",
     \"branch_name\": \"wt-gateway\", \"status\": \"offline\",
     \"current_task_id\": None, \"last_heartbeat\": \"2026-04-06T09:15:00Z\",
     \"created_at\": \"2026-04-06T08:00:00Z\"}
]

with respx.mock:
    respx.get(\"http://localhost:8000/api/v1/projects\").mock(return_value=Response(200, json=PROJECTS))
    respx.get(\"http://localhost:8000/api/v1/projects/aaa-bbb/worktrees\").mock(return_value=Response(200, json=WORKTREES))
    r = CliRunner().invoke(app, [\"agents\", \"list\", \"--project\", \"my-project\", \"--status\", \"active\"])
    print(r.output)
"
```

```output

Agents for 'my-project' (1)

  ● wt-board             w1w1w1w1  active     wt-board
    task: t1t1t1t1  heartbeat: 2026-04-07T12:30:00

```
