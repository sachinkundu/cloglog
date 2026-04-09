# T-117 Auto-Attach Documents + T-152 PR Merge Status

*2026-04-09T08:10:18Z by Showboat 0.6.1*
<!-- showboat-id: 7e61b684-bacd-43a6-aaf2-bbde7fcaab87 -->

## T-117: Auto-attach documents when spec/plan tasks move to review

When a spec or plan task is moved to review with a pr_url, a Document record is
automatically created and attached to the parent feature. Deduplication prevents
duplicate documents when the same task moves to review again with the same URL.

## T-152: PR merge status field

New `pr_merged` boolean field on Task model (default false). Exposed in all
task response schemas. Settable via PATCH. Includes Alembic migration.

## Proof: Running the new tests

```bash
uv run pytest tests/board/test_services.py -k "auto_attach" -v --no-header 2>&1 | grep -E "PASSED|FAILED|ERROR|test_"
```

```output
tests/board/test_services.py::test_auto_attach_spec_on_review PASSED     [ 25%]
tests/board/test_services.py::test_auto_attach_plan_on_review PASSED     [ 50%]
tests/board/test_services.py::test_auto_attach_skips_impl_tasks PASSED   [ 75%]
tests/board/test_services.py::test_auto_attach_deduplicates PASSED       [100%]
```

```bash
uv run pytest tests/board/test_routes.py -k "auto_attach or pr_merged" -v --no-header 2>&1 | grep -E "PASSED|FAILED|ERROR|test_"
```

```output
tests/board/test_routes.py::test_update_spec_task_to_review_auto_attaches_document PASSED [ 20%]
tests/board/test_routes.py::test_task_response_includes_pr_merged PASSED [ 40%]
tests/board/test_routes.py::test_update_pr_merged PASSED                 [ 60%]
tests/board/test_routes.py::test_board_includes_pr_merged PASSED         [ 80%]
tests/board/test_routes.py::test_active_tasks_includes_pr_merged PASSED  [100%]
```

## Full board test suite (baseline + new)

```bash
uv run pytest tests/board/ --no-header -q 2>&1 | tail -1 | sed "s/in [0-9.]*s/in Xs/"
```

```output
101 passed in Xs
```
