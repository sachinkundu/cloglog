# T-262: worktree agents shutting down can now build the prs map (T-NNN -> PR URL) from get_my_tasks() rows because TaskInfo exposes both number and pr_url. Supervisors get rich PR attribution in agent_unregistered without falling back to gh pr list.

*2026-04-26T09:54:13Z by Showboat 0.6.1*
<!-- showboat-id: 43f67079-d30b-4ca5-8896-4d61b7f33f39 -->

Context — Codex review round 2 (PR #220, 2026-04-26): the protocol said agents build prs by walking get_my_tasks() and reading each row's pr_url. But TaskInfo only had id/title/description/status/priority/artifact_path. Agents had no field to read for the URL and no field to use as the T-NNN map key. The documented contract was unimplementable from the codebase as it stood.

Proof 1 — TaskInfo Pydantic model now declares number and pr_url. We import the actual class used by the route handler and inspect its model_fields. This is the exact response shape clients see.

```bash

uv run --quiet python - <<PY
import sys
sys.path.insert(0, ".")
from src.agent.schemas import TaskInfo

fields = TaskInfo.model_fields
assert "number" in fields, "TaskInfo missing number"
assert "pr_url" in fields, "TaskInfo missing pr_url"
assert "id" in fields and "title" in fields, "regression on existing fields"

# pr_url is optional (nullable) — tasks before review have no PR yet.
pr_field = fields["pr_url"]
assert pr_field.is_required() is False, "pr_url should be optional"

# number is required and integer-typed (T-NNN suffix).
num_field = fields["number"]
assert num_field.is_required() is True, "number should be required"
assert num_field.annotation is int, f"number should be int, got {num_field.annotation}"

print("OK TaskInfo fields: " + ", ".join(sorted(fields.keys())))
print("OK number is required int; pr_url is optional str")
PY

```

```output
OK TaskInfo fields: artifact_path, description, id, number, pr_url, priority, status, title
OK number is required int; pr_url is optional str
```

Proof 2 — the route handler returns TaskInfo.model_validate(t) on each task row. Since number and pr_url are columns on the SQLAlchemy Task model (src/board/models.py:128 + line 136 — pr_url and number), Pydantic's from_attributes=True config copies them into the response. AST inspection confirms the route function still constructs TaskInfo this way.

```bash

python3 - <<PY
import ast, pathlib

src = pathlib.Path("src/agent/routes.py").read_text()
tree = ast.parse(src)

# Find the get_tasks function decorated as GET /agents/{worktree_id}/tasks.
# Route handler is async, so use AsyncFunctionDef.
fn = next(
    n for n in ast.walk(tree)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "get_tasks"
)

# The decorator must reference /agents/{worktree_id}/tasks with TaskInfo as the response model.
deco_src = ast.unparse(fn.decorator_list[0])
assert "/agents/{worktree_id}/tasks" in deco_src, deco_src
assert "TaskInfo" in deco_src, deco_src

# The body must construct TaskInfo.model_validate(t) per task row — that is the
# bridge that copies number + pr_url off the SQLAlchemy row into the response.
body_src = ast.unparse(fn)
assert "TaskInfo.model_validate" in body_src, body_src
print("OK get_tasks returns list[TaskInfo] via TaskInfo.model_validate(t)")
print("    — number + pr_url copied off the Task SQLAlchemy row by from_attributes=True")
PY

```

```output
OK get_tasks returns list[TaskInfo] via TaskInfo.model_validate(t)
    — number + pr_url copied off the Task SQLAlchemy row by from_attributes=True
```

Proof 3 — the OpenAPI baseline (docs/contracts/baseline.openapi.yaml) lists number and pr_url under TaskInfo, with number required and pr_url nullable. Contract-check (make quality step) recomputes the live OpenAPI from the FastAPI app and compares; baseline drift fails the gate. We parse the YAML directly to prove the schema entries are present.

```bash

uv run --quiet python - <<PY
import pathlib, sys
import yaml

contract = yaml.safe_load(pathlib.Path("docs/contracts/baseline.openapi.yaml").read_text())
ti = contract["components"]["schemas"]["TaskInfo"]

props = ti["properties"]
assert "number" in props, "OpenAPI TaskInfo missing number"
assert "pr_url" in props, "OpenAPI TaskInfo missing pr_url"

required = ti.get("required", [])
assert "number" in required, "number should be required in contract"
assert "pr_url" not in required, "pr_url should be optional in contract"

# pr_url nullable shape — anyOf [string, null]
pr = props["pr_url"]
types = sorted(t.get("type") for t in pr.get("anyOf", []))
assert types == ["null", "string"], f"pr_url should be anyOf string|null, got {types}"

print("OK contract baseline TaskInfo declares number (required int) and pr_url (anyOf string|null)")
PY

```

```output
OK contract baseline TaskInfo declares number (required int) and pr_url (anyOf string|null)
```

Proof 4 — end-to-end demonstration of the prs-map construction the docs promise. We instantiate TaskInfo with realistic data (one task with a PR, one without), then build the {T-NNN: pr_url} map exactly as the agent prompt instructs: walk rows, key at f"T-{row.number}", omit rows whose pr_url is None.

```bash

uv run --quiet python - <<PY
import sys, uuid
sys.path.insert(0, ".")
from src.agent.schemas import TaskInfo

# Simulate what get_my_tasks() returns at shutdown — two completed tasks.
rows = [
    TaskInfo(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        number=262,
        title="T-262 task",
        description="enrich agent_unregistered",
        status="review",
        priority="normal",
        pr_url="https://github.com/sachinkundu/cloglog/pull/220",
    ),
    TaskInfo(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        number=263,
        title="plan task with skip_pr=True",
        description="no PR",
        status="review",
        priority="normal",
        pr_url=None,
    ),
]

# Build the prs map exactly as plugins/cloglog/skills/launch/SKILL.md instructs.
prs = {f"T-{r.number}": r.pr_url for r in rows if r.pr_url is not None}

assert prs == {"T-262": "https://github.com/sachinkundu/cloglog/pull/220"}, prs
print("OK prs map built from get_my_tasks() rows:")
for k, v in prs.items():
    print(f"    {k} -> {v}")
print("OK no-PR row (T-263) correctly omitted, not mapped to null")
PY

```

```output
OK prs map built from get_my_tasks() rows:
    T-262 -> https://github.com/sachinkundu/cloglog/pull/220
OK no-PR row (T-263) correctly omitted, not mapped to null
```

Proof 5 — the regression pin test_task_info_exposes_fields_needed_for_prs_map runs and passes. This is the test gate at make quality time that fails if a future schema slim-down removes either field without removing the docs in lockstep.

```bash

uv run --quiet python - <<PY
import sys
sys.path.insert(0, ".")
# Plain import bypasses pytest.conftest auto-discovery (same pattern as the
# T-290 demo) so the session-autouse Postgres fixture does NOT fire on verify.
from tests import test_agent_lifecycle_pr_signals as T

T.test_task_info_exposes_fields_needed_for_prs_map()
print("OK test_task_info_exposes_fields_needed_for_prs_map passed")

T.test_lifecycle_spec_documents_prs_map_in_unregister()
print("OK lifecycle spec carries prs example + Option A justification")

T.test_launch_skill_prompts_prs_map_in_unregister()
print("OK launch SKILL prompt template carries prs map + get_my_tasks build instruction")
PY

```

```output
OK test_task_info_exposes_fields_needed_for_prs_map passed
OK lifecycle spec carries prs example + Option A justification
OK launch SKILL prompt template carries prs map + get_my_tasks build instruction
```
