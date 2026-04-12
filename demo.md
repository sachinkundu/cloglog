# Project Stats Endpoint Demo

## Setup: project with tasks in various statuses

Created 5 tasks: 2 backlog, 1 in_progress, 1 review, 1 done
Created 2 features (Feature Beta has all tasks done -> should count as done)

## 1. GET /projects/{id}/stats
```json
{
  "project_id": "a2e95e19-b49b-416a-a900-c7df54f55a20",
  "task_counts": {
    "backlog": 2,
    "prioritized": 0,
    "in_progress": 1,
    "review": 1,
    "done": 1,
    "total": 5
  },
  "agent_count": 0,
  "feature_completion_percentage": 0.0
}
```

## 2. Stats for nonexistent project (404)
```json
{"detail":"Project not found"}
HTTP 404
```

## 3. Mark Feature Beta as done and check updated completion

Marked Feature Beta as done.
```json
{
  "feature_completion_percentage": 50.0,
  "task_counts": {
    "total": 5,
    "done": 1
  }
}
```

## Test Results
```
.claude/worktrees/wt-fake-stats/tests/board/test_routes.py::test_get_project_stats_empty_project PASSED [ 16%]
.claude/worktrees/wt-fake-stats/tests/board/test_routes.py::test_get_project_stats_task_counts_by_status PASSED [ 33%]
.claude/worktrees/wt-fake-stats/tests/board/test_routes.py::test_get_project_stats_feature_completion_percentage PASSED [ 50%]
.claude/worktrees/wt-fake-stats/tests/board/test_routes.py::test_get_project_stats_agent_count PASSED [ 66%]
.claude/worktrees/wt-fake-stats/tests/board/test_routes.py::test_get_project_stats_not_found PASSED [ 83%]
.claude/worktrees/wt-fake-stats/tests/board/test_routes.py::test_get_project_stats_retired_tasks_excluded PASSED [100%]
======================= 6 passed, 80 deselected in 1.56s =======================
```
