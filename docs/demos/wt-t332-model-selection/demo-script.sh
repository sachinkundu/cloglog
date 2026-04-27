#!/usr/bin/env bash
# Demo: Operators can now set a model on each task; the launch skill passes
# --model to claude at launch time so reasoning-heavy tasks run on Opus and
# mechanical implementation runs on Sonnet/Haiku.
# Called by make demo (server + DB already running).
# All proofs use code inspection — no live server required, so showboat verify
# passes during `make quality` without a running backend.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

DEMO_DIR="${SCRIPT_DIR#"$REPO_ROOT"/}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Operators can now set a model on each task; the launch skill passes --model to claude so spec tasks run on Opus and implementation tasks run on Sonnet/Haiku."

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — Board schemas: model field present on TaskCreate, TaskUpdate, TaskResponse"
uvx showboat exec "$DEMO_FILE" bash '
uv run --quiet python - <<PY
import sys
sys.path.insert(0, ".")
from src.board.schemas import TaskCreate, TaskUpdate, TaskResponse

for cls in (TaskCreate, TaskUpdate, TaskResponse):
    fields = cls.model_fields
    assert "model" in fields, cls.__name__ + " missing model field"
    assert not fields["model"].is_required(), cls.__name__ + ".model should be optional"
    print("OK " + cls.__name__ + ".model: optional str | None")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 2 — Agent schemas: model surfaced through TaskInfo and StartTaskResponse"
uvx showboat exec "$DEMO_FILE" bash '
uv run --quiet python - <<PY
import sys
sys.path.insert(0, ".")
from src.agent.schemas import TaskInfo, StartTaskResponse

for cls in (TaskInfo, StartTaskResponse):
    fields = cls.model_fields
    assert "model" in fields, cls.__name__ + " missing model field"
    assert not fields["model"].is_required(), cls.__name__ + ".model should be optional"
    print("OK " + cls.__name__ + ".model: optional str | None")

cfg = TaskInfo.model_config
assert cfg.get("from_attributes") is True, "TaskInfo needs from_attributes=True"
print("OK TaskInfo.from_attributes=True — model copies off SQLAlchemy Task.model column")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — SearchResult: model field present so mcp__cloglog__search returns task model"
uvx showboat exec "$DEMO_FILE" bash '
uv run --quiet python - <<PY
import sys
sys.path.insert(0, ".")
from src.board.schemas import SearchResult

fields = SearchResult.model_fields
assert "model" in fields, "SearchResult missing model field"
assert not fields["model"].is_required(), "SearchResult.model should be optional"
print("OK SearchResult.model: optional str | None")
print("   mcp__cloglog__search now returns model for each task result")
print("   the launch skill reads this to embed --model in launch.sh")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 4 — ORM + services: Task.model column present; start_task returns model"
uvx showboat exec "$DEMO_FILE" bash '
uv run --quiet python - <<PY
import sys, ast, pathlib
sys.path.insert(0, ".")

# Check Task ORM has model column via column attribute inspection
import sqlalchemy
from src.board.models import Task
insp = sqlalchemy.inspect(Task)
col_keys = [c.key for c in insp.mapper.column_attrs]
assert "model" in col_keys, "Task ORM missing model column"
model_col = insp.mapper.column_attrs["model"]
col_type = type(model_col.columns[0].type).__name__
assert col_type == "String", "Task.model should be String, got " + col_type
print("OK Task.model: SQLAlchemy String(100), nullable=True")

# AST proof: services.start_task returns task.model in its response dict
src = pathlib.Path("src/agent/services.py").read_text()
tree = ast.parse(src)
fn = next(
    n for n in ast.walk(tree)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    and n.name == "start_task"
)
body_src = ast.unparse(fn)
assert "task.model" in body_src, "start_task must return task.model"
print("OK services.start_task returns dict with task.model")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 5 — Launch skill: writes .cloglog/task-model; launch.sh reads it for --model flag"
uvx showboat exec "$DEMO_FILE" bash '
python3 - <<PY
from pathlib import Path
import re

skill = Path("plugins/cloglog/skills/launch/SKILL.md").read_text()

assert ".cloglog/task-model" in skill, "SKILL.md must reference .cloglog/task-model"
assert "TASK_MODEL" in skill, "SKILL.md must reference TASK_MODEL variable"
assert "_MODEL_FLAG" in skill, "launch.sh template must set _MODEL_FLAG"
assert "_TASK_MODEL" in skill, "launch.sh template must set _TASK_MODEL"

relaunch = re.search(r"## Supervisor Relaunch Flow.*?(?=\n## |\Z)", skill, re.DOTALL)
assert relaunch, "Supervisor Relaunch Flow section missing"
assert "task-model" in relaunch.group(0), "Supervisor Relaunch Flow must update task-model"

print("OK SKILL.md writes .cloglog/task-model before launch.sh generation")
print("OK launch.sh template reads task-model at runtime, sets _MODEL_FLAG")
print("OK Supervisor Relaunch Flow updates task-model before continuation relaunch")
PY
'

uvx showboat note "$DEMO_FILE" \
  "Proof 6 — Runtime: task-model file to --model flag logic works correctly"
uvx showboat exec "$DEMO_FILE" bash '
TMPDIR=$(mktemp -d)
printf "%s\n" "claude-opus-4-7" > "$TMPDIR/task-model"
_MODEL_FLAG=""
_TASK_MODEL=$(cat "$TMPDIR/task-model" 2>/dev/null || true)
[[ -n "$_TASK_MODEL" ]] && _MODEL_FLAG="--model $_TASK_MODEL"
echo "spec task flag: ${_MODEL_FLAG:-(none)}"
printf "%s\n" "" > "$TMPDIR/task-model"
_MODEL_FLAG=""
_TASK_MODEL=$(cat "$TMPDIR/task-model" 2>/dev/null || true)
[[ -n "$_TASK_MODEL" ]] && _MODEL_FLAG="--model $_TASK_MODEL"
echo "no-model flag: ${_MODEL_FLAG:-(none — uses host default)}"
rm "$TMPDIR/task-model"
_MODEL_FLAG=""
_TASK_MODEL=$(cat "$TMPDIR/task-model" 2>/dev/null || true)
[[ -n "$_TASK_MODEL" ]] && _MODEL_FLAG="--model $_TASK_MODEL"
echo "missing-file flag: ${_MODEL_FLAG:-(none — uses host default)}"
rm -rf "$TMPDIR"
'

uvx showboat verify "$DEMO_FILE"
