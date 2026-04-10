# Search Filters Demo

*2026-04-10T11:45:12Z by Showboat 0.6.1*
<!-- showboat-id: a8e4ac7d-cd63-44ff-8c82-ed9778fb7beb -->

## Backend: status_filter query param

New status_filter query parameter restricts search results by task status.
When set, only tasks are searched (epics/features don't have the same status semantics).

Supported filters:
- is:open → backlog, in_progress, review
- is:closed → done
- is:archived → archived

```bash
uv run pytest /home/sachin/code/cloglog/.claude/worktrees/wt-ui-search/tests/board/test_routes.py -v -k search 2>&1 | grep -E "PASSED|FAILED" | sed "s/.*:://; s/ \[.*//; s/[[:space:]]*$//"
```

```output
test_search_by_title PASSED
test_search_case_insensitive PASSED
test_search_by_entity_number PASSED
test_search_by_bare_number PASSED
test_search_type_prefix_filters PASSED
test_search_respects_limit PASSED
test_search_empty_query_rejected PASSED
test_search_invalid_project_404 PASSED
test_search_includes_breadcrumbs PASSED
test_search_returns_all_entity_types PASSED
test_search_status_filter_open PASSED
test_search_status_filter_closed PASSED
test_search_status_filter_excludes_epics_features PASSED
test_search_no_status_filter_returns_all PASSED
```

## Frontend: qualifier parser + hook + widget

parseSearchQualifiers() extracts is: qualifiers from search input and maps to status arrays.
Filter pill badge shows next to search input when qualifier is active.

```bash
cd /home/sachin/code/cloglog/.claude/worktrees/wt-ui-search/frontend && npx vitest run src/lib/searchQualifiers.test.ts src/hooks/useSearch.test.ts src/components/SearchWidget.test.tsx 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -E "Test Files|Tests "
```

```output
 Test Files  3 passed (3)
      Tests  33 passed (33)
```
