# Search Filters Demo

## Setup: project with tasks in backlog, in_progress, done

Created 3 tasks: backlog, in_progress, done

## 1. Search without filter (returns all 3)
```json
{
  "title": "Agent auth backlog task",
  "status": "backlog"
}
{
  "title": "Agent deploy in progress",
  "status": "in_progress"
}
{
  "title": "Agent migration done",
  "status": "done"
}
```

## 2. is:open filter (backlog + in_progress only)
```json
{
  "title": "Agent auth backlog task",
  "status": "backlog"
}
{
  "title": "Agent deploy in progress",
  "status": "in_progress"
}
```

## 3. is:closed filter (done only)
```json
{
  "title": "Agent migration done",
  "status": "done"
}
```

## Frontend qualifier parsing

- `is:open agent` → q=agent&status_filter=backlog&status_filter=in_progress&status_filter=review
- `is:closed migration` → q=migration&status_filter=done
- `is:archived old` → q=old&status_filter=archived

Filter pill badge shows next to search input when qualifier is active.

## Test Results

### Backend (14 search tests, 4 new)
```
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_by_title PASSED [  7%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_case_insensitive PASSED [ 14%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_by_entity_number PASSED [ 21%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_by_bare_number PASSED [ 28%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_type_prefix_filters PASSED [ 35%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_respects_limit PASSED [ 42%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_empty_query_rejected PASSED [ 50%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_invalid_project_404 PASSED [ 57%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_includes_breadcrumbs PASSED [ 64%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_returns_all_entity_types PASSED [ 71%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_status_filter_open PASSED [ 78%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_status_filter_closed PASSED [ 85%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_status_filter_excludes_epics_features PASSED [ 92%]
.claude/worktrees/wt-ui-search/tests/board/test_routes.py::test_search_no_status_filter_returns_all PASSED [100%]
====================== 14 passed, 54 deselected in 2.83s =======================
```

### Frontend (33 tests, 12 new)
```
 RUN  v4.1.2 /home/sachin/code/cloglog/.claude/worktrees/wt-ui-search/frontend


 Test Files  3 passed (3)
      Tests  33 passed (33)
   Start at  14:33:06
   Duration  1.36s (transform 145ms, setup 168ms, import 311ms, tests 453ms, environment 1.86s)

```
