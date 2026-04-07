"""Tests for Gateway CLI scaffold."""

from __future__ import annotations

import json

import respx
from httpx import Response
from typer.testing import CliRunner

from src.gateway.cli import app

runner = CliRunner()

# --- Shared test fixtures ---

PROJECT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TASK_ID = "11111111-2222-3333-4444-555555555555"
WORKTREE_ID = "99999999-8888-7777-6666-555555555555"
BASE = "http://localhost:8000"

MOCK_PROJECTS = [{"id": PROJECT_ID, "name": "testproj", "status": "active"}]

MOCK_SEARCH_RESULT = {
    "query": "T-101",
    "results": [
        {
            "id": TASK_ID,
            "type": "task",
            "title": "Write design spec",
            "number": 101,
            "status": "in_progress",
        }
    ],
    "total": 1,
}

MOCK_BACKLOG = [
    {
        "epic": {
            "id": "e1e1e1e1-0000-0000-0000-000000000000",
            "title": "Dev Experience",
            "number": 3,
            "project_id": PROJECT_ID,
            "description": "",
            "bounded_context": "",
            "context_description": "",
            "status": "planned",
            "position": 0,
            "color": "#0ea5e9",
            "created_at": "2026-04-06T10:00:00Z",
        },
        "features": [
            {
                "feature": {
                    "id": "f1f1f1f1-0000-0000-0000-000000000000",
                    "epic_id": "e1e1e1e1-0000-0000-0000-000000000000",
                    "title": "Task Assignment CLI",
                    "number": 9,
                    "description": "",
                    "status": "planned",
                    "position": 0,
                    "created_at": "2026-04-06T10:00:00Z",
                },
                "tasks": [
                    {
                        "id": TASK_ID,
                        "number": 101,
                        "title": "Write design spec",
                        "status": "in_progress",
                        "priority": "normal",
                        "worktree_id": WORKTREE_ID,
                    },
                    {
                        "id": "22222222-3333-4444-5555-666666666666",
                        "number": 102,
                        "title": "Write impl plan",
                        "status": "backlog",
                        "priority": "normal",
                        "worktree_id": None,
                    },
                    {
                        "id": "33333333-4444-5555-6666-777777777777",
                        "number": 103,
                        "title": "Implement feature",
                        "status": "done",
                        "priority": "normal",
                        "worktree_id": None,
                    },
                ],
                "task_counts": {"total": 3, "done": 1},
            }
        ],
        "task_counts": {"total": 3, "done": 1},
    }
]

MOCK_WORKTREES = [
    {
        "id": WORKTREE_ID,
        "worktree_path": "/home/user/code/cloglog/.claude/worktrees/wt-assign",
        "branch_name": "wt-assign",
        "status": "active",
    }
]

MOCK_WORKTREES_FULL = [
    {
        "id": WORKTREE_ID,
        "project_id": PROJECT_ID,
        "name": "wt-assign",
        "worktree_path": "/home/user/code/cloglog/.claude/worktrees/wt-assign",
        "branch_name": "wt-assign",
        "status": "active",
        "current_task_id": TASK_ID,
        "last_heartbeat": "2026-04-07T12:00:00Z",
        "created_at": "2026-04-06T10:00:00Z",
    },
    {
        "id": "88888888-7777-6666-5555-444444444444",
        "project_id": PROJECT_ID,
        "name": "wt-board",
        "worktree_path": "/home/user/code/cloglog/.claude/worktrees/wt-board",
        "branch_name": "wt-board",
        "status": "offline",
        "current_task_id": None,
        "last_heartbeat": "2026-04-06T09:00:00Z",
        "created_at": "2026-04-06T08:00:00Z",
    },
]

MOCK_TASK_PATCH = {
    "id": TASK_ID,
    "feature_id": "f1f1f1f1-0000-0000-0000-000000000000",
    "title": "Write design spec",
    "description": "",
    "status": "in_progress",
    "priority": "normal",
    "worktree_id": WORKTREE_ID,
    "position": 0,
    "number": 101,
    "archived": False,
    "created_at": "2026-04-06T10:00:00Z",
    "updated_at": "2026-04-06T10:00:00Z",
}


# --- Existing tests ---


def test_cli_version() -> None:
    """CLI --version flag prints the version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_health_command() -> None:
    """CLI health command prints status."""
    result = runner.invoke(app, ["health", "--url", "http://localhost:8000"])
    assert result.exit_code != 2


def test_cli_projects_list_command() -> None:
    """CLI projects list command exists."""
    result = runner.invoke(app, ["projects", "list", "--url", "http://localhost:8000"])
    assert result.exit_code != 2


def test_cli_projects_create_command() -> None:
    """CLI projects create command exists and requires --name."""
    result = runner.invoke(app, ["projects", "create", "--url", "http://localhost:8000"])
    assert result.exit_code == 2


# --- Task command existence tests ---


def test_tasks_list_command_exists() -> None:
    """tasks list command exists and requires --project."""
    result = runner.invoke(app, ["tasks", "list"])
    assert result.exit_code == 2  # missing required --project


def test_tasks_show_command_exists() -> None:
    """tasks show command exists and requires --task and --project."""
    result = runner.invoke(app, ["tasks", "show"])
    assert result.exit_code == 2


def test_tasks_assign_command_exists() -> None:
    """tasks assign command exists."""
    result = runner.invoke(app, ["tasks", "assign"])
    assert result.exit_code == 2


def test_tasks_unassign_command_exists() -> None:
    """tasks unassign command exists."""
    result = runner.invoke(app, ["tasks", "unassign"])
    assert result.exit_code == 2


def test_tasks_start_command_exists() -> None:
    """tasks start command exists."""
    result = runner.invoke(app, ["tasks", "start"])
    assert result.exit_code == 2


def test_tasks_complete_command_exists() -> None:
    """tasks complete command exists."""
    result = runner.invoke(app, ["tasks", "complete"])
    assert result.exit_code == 2


def test_tasks_status_command_exists() -> None:
    """tasks status command exists."""
    result = runner.invoke(app, ["tasks", "status"])
    assert result.exit_code == 2


# --- Integration tests with respx mocks ---


@respx.mock
def test_tasks_list_table_output() -> None:
    """tasks list displays tasks grouped by status."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/backlog").mock(
        return_value=Response(200, json=MOCK_BACKLOG)
    )

    result = runner.invoke(app, ["tasks", "list", "--project", "testproj", "--url", BASE])
    assert result.exit_code == 0
    assert "In Progress (1)" in result.output
    assert "T-101" in result.output
    assert "Write design spec" in result.output
    # Done tasks should be hidden by default
    assert "hidden" in result.output


@respx.mock
def test_tasks_list_json_output() -> None:
    """tasks list --json outputs valid JSON."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/backlog").mock(
        return_value=Response(200, json=MOCK_BACKLOG)
    )

    result = runner.invoke(app, ["tasks", "list", "--project", "testproj", "--url", BASE, "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 3
    assert data[0]["number"] == 101


@respx.mock
def test_tasks_list_status_filter() -> None:
    """tasks list --status filters to one status."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/backlog").mock(
        return_value=Response(200, json=MOCK_BACKLOG)
    )

    result = runner.invoke(
        app,
        ["tasks", "list", "--project", "testproj", "--url", BASE, "--status", "in_progress"],
    )
    assert result.exit_code == 0
    assert "T-101" in result.output
    assert "T-102" not in result.output


@respx.mock
def test_tasks_list_all_shows_done() -> None:
    """tasks list --all includes done tasks."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/backlog").mock(
        return_value=Response(200, json=MOCK_BACKLOG)
    )

    result = runner.invoke(app, ["tasks", "list", "--project", "testproj", "--url", BASE, "--all"])
    assert result.exit_code == 0
    assert "T-103" in result.output
    assert "hidden" not in result.output


@respx.mock
def test_tasks_show_detail() -> None:
    """tasks show displays task detail."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-101"}).mock(
        return_value=Response(200, json=MOCK_SEARCH_RESULT)
    )
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/backlog").mock(
        return_value=Response(200, json=MOCK_BACKLOG)
    )
    respx.get(f"{BASE}/api/v1/tasks/{TASK_ID}/notes").mock(return_value=Response(200, json=[]))

    result = runner.invoke(
        app, ["tasks", "show", "--task", "T-101", "--project", "testproj", "--url", BASE]
    )
    assert result.exit_code == 0
    assert "T-101: Write design spec" in result.output
    assert "in_progress" in result.output
    assert "F-9 Task Assignment CLI" in result.output
    assert "E-3 Dev Experience" in result.output


@respx.mock
def test_tasks_show_json() -> None:
    """tasks show --json outputs valid JSON with notes."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-101"}).mock(
        return_value=Response(200, json=MOCK_SEARCH_RESULT)
    )
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/backlog").mock(
        return_value=Response(200, json=MOCK_BACKLOG)
    )
    respx.get(f"{BASE}/api/v1/tasks/{TASK_ID}/notes").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": "n1",
                    "task_id": TASK_ID,
                    "note": "Test note",
                    "created_at": "2026-04-06T11:00:00Z",
                }
            ],
        )
    )

    result = runner.invoke(
        app, ["tasks", "show", "--task", "T-101", "--project", "testproj", "--url", BASE, "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["number"] == 101
    assert len(data["notes"]) == 1


@respx.mock
def test_tasks_assign_success() -> None:
    """tasks assign sets worktree_id on the task."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-101"}).mock(
        return_value=Response(200, json=MOCK_SEARCH_RESULT)
    )
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/worktrees").mock(
        return_value=Response(200, json=MOCK_WORKTREES)
    )
    respx.patch(f"{BASE}/api/v1/tasks/{TASK_ID}").mock(
        return_value=Response(200, json=MOCK_TASK_PATCH)
    )

    result = runner.invoke(
        app,
        [
            "tasks",
            "assign",
            "--task",
            "T-101",
            "--project",
            "testproj",
            "--worktree",
            "wt-assign",
            "--url",
            BASE,
        ],
    )
    assert result.exit_code == 0
    assert "Assigned T-101 to worktree wt-assign" in result.output


@respx.mock
def test_tasks_unassign_success() -> None:
    """tasks unassign clears worktree_id."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-101"}).mock(
        return_value=Response(200, json=MOCK_SEARCH_RESULT)
    )
    respx.patch(f"{BASE}/api/v1/tasks/{TASK_ID}").mock(
        return_value=Response(200, json={**MOCK_TASK_PATCH, "worktree_id": None})
    )

    result = runner.invoke(
        app,
        ["tasks", "unassign", "--task", "T-101", "--project", "testproj", "--url", BASE],
    )
    assert result.exit_code == 0
    assert "Unassigned T-101" in result.output


@respx.mock
def test_tasks_start_success() -> None:
    """tasks start sets status to in_progress."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-101"}).mock(
        return_value=Response(200, json=MOCK_SEARCH_RESULT)
    )
    respx.patch(f"{BASE}/api/v1/tasks/{TASK_ID}").mock(
        return_value=Response(200, json={**MOCK_TASK_PATCH, "status": "in_progress"})
    )

    result = runner.invoke(
        app,
        ["tasks", "start", "--task", "T-101", "--project", "testproj", "--url", BASE],
    )
    assert result.exit_code == 0
    assert "T-101" in result.output
    assert "in_progress" in result.output


@respx.mock
def test_tasks_complete_success() -> None:
    """tasks complete sets status to done."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-101"}).mock(
        return_value=Response(200, json=MOCK_SEARCH_RESULT)
    )
    respx.patch(f"{BASE}/api/v1/tasks/{TASK_ID}").mock(
        return_value=Response(200, json={**MOCK_TASK_PATCH, "status": "done"})
    )

    result = runner.invoke(
        app,
        ["tasks", "complete", "--task", "T-101", "--project", "testproj", "--url", BASE],
    )
    assert result.exit_code == 0
    assert "T-101" in result.output
    assert "done" in result.output


@respx.mock
def test_tasks_status_set_review() -> None:
    """tasks status --set review works."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-101"}).mock(
        return_value=Response(200, json=MOCK_SEARCH_RESULT)
    )
    respx.patch(f"{BASE}/api/v1/tasks/{TASK_ID}").mock(
        return_value=Response(200, json={**MOCK_TASK_PATCH, "status": "review"})
    )

    result = runner.invoke(
        app,
        [
            "tasks",
            "status",
            "--task",
            "T-101",
            "--project",
            "testproj",
            "--set",
            "review",
            "--url",
            BASE,
        ],
    )
    assert result.exit_code == 0
    assert "T-101" in result.output
    assert "review" in result.output


def test_tasks_status_invalid() -> None:
    """tasks status --set with invalid value exits 1."""
    result = runner.invoke(
        app,
        [
            "tasks",
            "status",
            "--task",
            "T-101",
            "--project",
            "testproj",
            "--set",
            "invalid_status",
            "--url",
            BASE,
        ],
    )
    assert result.exit_code == 1
    assert "invalid status" in result.output.lower()


@respx.mock
def test_tasks_list_unknown_project() -> None:
    """tasks list with unknown project exits 1."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=[]))

    result = runner.invoke(app, ["tasks", "list", "--project", "nonexistent", "--url", BASE])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


@respx.mock
def test_tasks_show_unknown_task() -> None:
    """tasks show with unknown task number exits 1."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/search", params={"q": "T-999"}).mock(
        return_value=Response(200, json={"query": "T-999", "results": [], "total": 0})
    )

    result = runner.invoke(
        app, ["tasks", "show", "--task", "T-999", "--project", "testproj", "--url", BASE]
    )
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# --- Agents command tests ---


def test_agents_list_command_exists() -> None:
    """agents list command exists and requires --project."""
    result = runner.invoke(app, ["agents", "list"])
    assert result.exit_code == 2  # missing required --project


@respx.mock
def test_agents_list_table_output() -> None:
    """agents list displays agents with status icons and details."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/worktrees").mock(
        return_value=Response(200, json=MOCK_WORKTREES_FULL)
    )

    result = runner.invoke(app, ["agents", "list", "--project", "testproj", "--url", BASE])
    assert result.exit_code == 0
    assert "wt-assign" in result.output
    assert "wt-board" in result.output
    assert "●" in result.output  # active icon
    assert "○" in result.output  # offline icon
    assert "Agents for 'testproj' (2)" in result.output


@respx.mock
def test_agents_list_json_output() -> None:
    """agents list --json outputs valid JSON."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/worktrees").mock(
        return_value=Response(200, json=MOCK_WORKTREES_FULL)
    )

    result = runner.invoke(
        app, ["agents", "list", "--project", "testproj", "--url", BASE, "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "wt-assign"


@respx.mock
def test_agents_list_status_filter() -> None:
    """agents list --status filters agents."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/worktrees").mock(
        return_value=Response(200, json=MOCK_WORKTREES_FULL)
    )

    result = runner.invoke(
        app,
        ["agents", "list", "--project", "testproj", "--url", BASE, "--status", "active"],
    )
    assert result.exit_code == 0
    assert "wt-assign" in result.output
    assert "wt-board" not in result.output


@respx.mock
def test_agents_list_empty() -> None:
    """agents list with no agents shows helpful message."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/worktrees").mock(
        return_value=Response(200, json=[])
    )

    result = runner.invoke(app, ["agents", "list", "--project", "testproj", "--url", BASE])
    assert result.exit_code == 0
    assert "No agents registered" in result.output


@respx.mock
def test_agents_list_unknown_project() -> None:
    """agents list with unknown project exits 1."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=[]))

    result = runner.invoke(app, ["agents", "list", "--project", "nonexistent", "--url", BASE])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


@respx.mock
def test_agents_list_shows_heartbeat() -> None:
    """agents list displays last heartbeat time."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/worktrees").mock(
        return_value=Response(200, json=MOCK_WORKTREES_FULL)
    )

    result = runner.invoke(app, ["agents", "list", "--project", "testproj", "--url", BASE])
    assert result.exit_code == 0
    assert "heartbeat:" in result.output
    assert "2026-04-07T12:00:00" in result.output


@respx.mock
def test_agents_list_shows_current_task() -> None:
    """agents list displays current task id."""
    respx.get(f"{BASE}/api/v1/projects").mock(return_value=Response(200, json=MOCK_PROJECTS))
    respx.get(f"{BASE}/api/v1/projects/{PROJECT_ID}/worktrees").mock(
        return_value=Response(200, json=MOCK_WORKTREES_FULL)
    )

    result = runner.invoke(app, ["agents", "list", "--project", "testproj", "--url", BASE])
    assert result.exit_code == 0
    assert "task:" in result.output
    assert "none" in result.output  # wt-board has no task
