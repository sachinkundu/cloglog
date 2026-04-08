# T-116 Demo: State Machine Guard Tests

## Test Execution

Running the new pipeline ordering tests plus the full guard test suite:

```bash
uv run pytest tests/agent/test_integration.py::TestPipelineOrderingAPI -v
```

### Results

```
tests/agent/test_integration.py::TestPipelineOrderingAPI::test_pipeline_ordering_spec_before_plan PASSED
tests/agent/test_integration.py::TestPipelineOrderingAPI::test_pipeline_ordering_plan_before_impl PASSED
tests/agent/test_integration.py::TestPipelineOrderingAPI::test_pipeline_ordering_allows_after_predecessor_done PASSED
```

## What Each Test Proves

### `test_pipeline_ordering_spec_before_plan`
Creates spec/plan/impl tasks under one feature. Tries to start the plan task before spec is done.
- **Result:** 409 with error message containing "spec" and "not done"

### `test_pipeline_ordering_plan_before_impl`
Completes the spec task, then tries to start impl before plan is done.
- **Result:** 409 with error message containing "plan" and "not done"

### `test_pipeline_ordering_allows_after_predecessor_done`
Full happy path: spec done -> plan starts -> plan done -> impl starts.
- **Result:** Each `start-task` returns 200 after its predecessor is done

## Full Suite

All 70 agent tests pass (67 pre-existing + 3 new):

```
============================== 70 passed in 8.56s ==============================
```
