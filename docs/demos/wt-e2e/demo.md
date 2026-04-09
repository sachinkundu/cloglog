# Demo: F-31 Multi-Agent Coordination E2E Test Suite

*2026-04-09 by wt-e2e agent*

92 E2E tests covering all 9 multi-agent coordination scenarios.

```bash
uv run pytest tests/e2e/ -v --tb=short 2>&1 | tail -20
```

```bash
uv run pytest tests/e2e/ --co -q 2>&1 | grep "test" | awk -F'::' '{print $1}' | sort | uniq -c | sort -rn
```

```bash
make quality 2>&1 | grep -E '(PASSED|FAILED|passed|failed|xfail|coverage|compliant)'
```

```bash
uv run pytest tests/e2e/ -v --tb=short 2>&1 | tail -20
```

```output
tests/e2e/test_project_lifecycle.py::test_board_view PASSED              [ 83%]
tests/e2e/test_project_lifecycle.py::test_bulk_import PASSED             [ 84%]
tests/e2e/test_state_machine.py::test_valid_transition_backlog_to_in_progress PASSED [ 86%]
tests/e2e/test_state_machine.py::test_valid_transition_in_progress_to_review PASSED [ 87%]
tests/e2e/test_state_machine.py::test_valid_transition_review_to_in_progress PASSED [ 88%]
tests/e2e/test_state_machine.py::test_dashboard_can_move_to_done PASSED  [ 89%]
tests/e2e/test_state_machine.py::test_skip_state_backlog_to_review_allowed PASSED [ 90%]
tests/e2e/test_state_machine.py::test_agent_cannot_move_to_done PASSED   [ 91%]
tests/e2e/test_state_machine.py::test_pipeline_ordering_spec_before_plan PASSED [ 92%]
tests/e2e/test_state_machine.py::test_pipeline_ordering_plan_before_impl PASSED [ 93%]
tests/e2e/test_state_machine.py::test_pipeline_ordering_standalone_tasks_skip PASSED [ 94%]
tests/e2e/test_state_machine.py::test_pr_url_required_for_review PASSED  [ 95%]
tests/e2e/test_state_machine.py::test_pr_url_reuse_blocked_same_feature PASSED [ 96%]
tests/e2e/test_state_machine.py::test_pr_url_reuse_blocked_cross_feature XFAIL [ 97%]
tests/e2e/test_state_machine.py::test_one_active_task_guard PASSED       [ 98%]
tests/e2e/test_state_machine.py::test_one_active_task_review_counts PASSED [100%]

=========================== short test summary info ============================
XFAIL tests/e2e/test_state_machine.py::test_pr_url_reuse_blocked_cross_feature - pr_url guard is currently feature-scoped, needs project-wide fix
======================== 92 passed, 1 xfailed in 19.36s ========================
```

```bash
uv run pytest tests/e2e/ --co -q 2>&1 | grep "test" | awk -F'::' '{print $1}' | sort | uniq -c | sort -rn
```

```output
     14 tests/e2e/test_state_machine.py
     13 tests/e2e/test_access_control.py
     10 tests/e2e/test_board_consistency.py
      9 tests/e2e/test_project_lifecycle.py
      8 tests/e2e/test_agent_lifecycle.py
      7 tests/e2e/test_multi_agent.py
      6 tests/e2e/test_project_isolation.py
      5 tests/e2e/test_messaging.py
      5 tests/e2e/test_document_flow.py
      5 tests/e2e/test_concurrency.py
      5 tests/e2e/test_auth.py
      4 tests/e2e/test_heartbeat_timeout.py
      1 tests/e2e/test_full_workflow.py
      1 tests/e2e/test_document_events.py
      1 93 tests collected in 0.05s
```

```bash
make quality 2>&1 | grep -E '(PASSED|FAILED|passed|failed|xfail|coverage|compliant)'
```

```output
All checks passed!
Required test coverage of 80% reached. Total coverage: 87.23%
328 passed, 1 xfailed in 48.04s
Contract check passed — backend matches all contract specifications
    compliant          ✓
── Quality gate: PASSED ────────────────
```
