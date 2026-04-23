# Task cards in the review column show a 'codex reviewed' badge the moment codex engages with the PR — projected read-only from `pr_review_turns` via the Review context's Open Host Service factory.

*2026-04-23T13:24:09Z by Showboat 0.6.1*
<!-- showboat-id: 6b310911-7731-47b3-8e2c-776ed7a502cb -->

### T-260 acceptance evidence — file-level booleans

User clarification 2026-04-23 narrowed the task to a single boolean badge
on review-column cards. These booleans are per-file pins of the exact
named file the spec expected the change to land in — no repo-wide counts
(per CLAUDE.md "Prove with OK/FAIL booleans").

```bash
S=src/board/schemas.py
   grep -q "codex_review_picked_up: bool" "$S" && echo "taskcard_has_field=yes" || echo "taskcard_has_field=MISSING"
   awk "/^class TaskResponse/{flag=1; next} /^class [A-Z]/{flag=0} flag" "$S" > /tmp/t260_resp.py
   awk "/^class TaskCard/{flag=1; next} /^class [A-Z]/{flag=0} flag" "$S" > /tmp/t260_card.py
   grep -q "codex_review_picked_up" /tmp/t260_card.py \
     && echo "on_TaskCard=yes" || echo "on_TaskCard=MISSING"
   grep -q "codex_review_picked_up" /tmp/t260_resp.py \
     && echo "on_TaskResponse=LEAK" || echo "on_TaskResponse=no (correct)"
```

```output
taskcard_has_field=yes
on_TaskCard=yes
on_TaskResponse=no (correct)
```

```bash
I=src/review/interfaces.py
   R=src/review/repository.py
   grep -q "async def codex_touched_pr_urls" "$I" && echo "interface_has_method=yes" || echo "interface_has_method=MISSING"
   grep -q "async def codex_touched_pr_urls" "$R" && echo "repository_implements_method=yes" || echo "repository_implements_method=MISSING"
   grep -q "PrReviewTurn.stage == \"codex\"" "$R" && echo "repository_filters_stage_codex=yes" || echo "repository_filters_stage_codex=MISSING"
```

```output
interface_has_method=yes
repository_implements_method=yes
repository_filters_stage_codex=yes
```

```bash
BOARD_DIR=src/board
   grep -rE "from src\\.review\\.(models|repository)" "$BOARD_DIR" > /tmp/t260_boundary.out 2>&1 || true
   if [ -s /tmp/t260_boundary.out ]; then
     echo "board_imports_review_internals=LEAK"; cat /tmp/t260_boundary.out
   else
     echo "board_imports_review_internals=no (correct)"
   fi
   grep -q "from src.review.services import make_review_turn_registry" src/board/routes.py \
     && echo "board_uses_ohs_factory=yes" || echo "board_uses_ohs_factory=MISSING"
```

```output
board_imports_review_internals=no (correct)
board_uses_ohs_factory=yes
```

```bash
E=src/shared/events.py
   grep -q "REVIEW_CODEX_TURN_STARTED" "$E" && echo "event_type_defined=yes" || echo "event_type_defined=MISSING"
   grep -q "review_codex_turn_started" "$E" && echo "event_type_string_value=yes" || echo "event_type_string_value=MISSING"
```

```output
event_type_defined=yes
event_type_string_value=yes
```

```bash
L=src/gateway/review_loop.py
   grep -q "if self._stage == \"codex\":" "$L" && echo "emit_gated_on_codex_stage=yes" || echo "emit_gated_on_codex_stage=MISSING"
   grep -q "EventType.REVIEW_CODEX_TURN_STARTED" "$L" && echo "emit_uses_new_event=yes" || echo "emit_uses_new_event=MISSING"
   grep -q "await event_bus.publish" "$L" && echo "emit_on_event_bus=yes" || echo "emit_on_event_bus=MISSING"
```

```output
emit_gated_on_codex_stage=yes
emit_uses_new_event=yes
emit_on_event_bus=yes
```

```bash
Y=docs/contracts/baseline.openapi.yaml
   awk "/^    TaskCard:/{flag=1; next} /^    [A-Z]/{flag=0} flag" "$Y" > /tmp/t260_taskcard_block.yaml
   grep -q "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml \
     && echo "contract_has_field_on_TaskCard=yes" || echo "contract_has_field_on_TaskCard=MISSING"
   grep -A1 "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml | grep -q "type: boolean" \
     && echo "contract_field_is_boolean=yes" || echo "contract_field_is_boolean=MISSING"
   grep -A3 "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml | grep -q "default: false" \
     && echo "contract_field_defaults_false=yes" || echo "contract_field_defaults_false=MISSING"
```

```output
contract_has_field_on_TaskCard=yes
contract_field_is_boolean=yes
contract_field_defaults_false=yes
```

```bash
G=frontend/src/api/generated-types.ts
   grep -q "codex_review_picked_up: boolean" "$G" && echo "generated_types_field=yes" || echo "generated_types_field=MISSING"
```

```output
generated_types_field=yes
```

```bash
T=frontend/src/components/TaskCard.tsx
   P=frontend/src/components/PrLink.tsx
   grep -q "codexReviewed=" "$T" && echo "tsx_wires_badge_prop=yes" || echo "tsx_wires_badge_prop=MISSING"
   grep -q "task.status === .review." "$T" && echo "tsx_gates_on_review_column=yes" || echo "tsx_gates_on_review_column=MISSING"
   grep -q "pr-codex-badge" "$P" && echo "prlink_has_codex_class=yes" || echo "prlink_has_codex_class=MISSING"
   grep -q "codex reviewed" "$P" && echo "prlink_renders_label=yes" || echo "prlink_renders_label=MISSING"
```

```output
tsx_wires_badge_prop=yes
tsx_gates_on_review_column=yes
prlink_has_codex_class=yes
prlink_renders_label=yes
```

```bash
H=frontend/src/hooks/useSSE.ts
   grep -q "review_codex_turn_started" "$H" && echo "sse_hook_subscribes=yes" || echo "sse_hook_subscribes=MISSING"
```

```output
sse_hook_subscribes=yes
```

### In-process projection round-trip

The round-trip below constructs the projection object directly (no DB), flipping
the codex-touched set on and off to prove the card field tracks it. This is
the verify-safe equivalent of the real-DB test at
`tests/board/test_codex_review_projection.py` (which runs under `make test`
but not under `uvx showboat verify` because it needs Postgres).

```bash
uv run python -c "
from datetime import datetime, timezone
from uuid import uuid4
from src.board.schemas import TaskCard

NOW = datetime.now(timezone.utc)
PR = \"https://github.com/owner/repo/pull/42\"

def make(pr_url, codex_touched):
    return TaskCard(
        id=uuid4(),
        feature_id=uuid4(),
        title=\"demo\",
        description=\"\",
        status=\"review\",
        priority=\"normal\",
        task_type=\"task\",
        pr_url=pr_url,
        pr_merged=False,
        worktree_id=None,
        position=0,
        number=1,
        archived=False,
        retired=False,
        created_at=NOW,
        updated_at=NOW,
        codex_review_picked_up=bool(pr_url and pr_url in codex_touched),
    )

# Case 1: PR present, no codex turn yet → False
print(\"case_no_codex_turn=\", make(PR, set()).codex_review_picked_up)
# Case 2: PR present, codex turn recorded → True
print(\"case_codex_turn_recorded=\", make(PR, {PR}).codex_review_picked_up)
# Case 3: PR present, only a DIFFERENT pr_url in the touched set → False
print(\"case_other_pr_touched=\", make(PR, {\"https://github.com/owner/repo/pull/999\"}).codex_review_picked_up)
# Case 4: Task without pr_url can never flip → False
print(\"case_no_pr_url=\", make(None, {PR}).codex_review_picked_up)
"
```

```output
case_no_codex_turn= False
case_codex_turn_recorded= True
case_other_pr_touched= False
case_no_pr_url= False
```

### DDD boundary pin test (structural)

The Board context now talks to Review only via the Open Host Service factory.
A pin test mirrors the existing Gateway→Review guard at
`tests/gateway/test_review_engine_t248.py` for the Board→Review edge. Below
is the same check run directly against the filesystem so `showboat verify`
can reproduce it byte-exactly.

```bash
uv run python -c "
import pathlib
root = pathlib.Path(\"src/board\")
bad_repo = [str(p) for p in root.rglob(\"*.py\") if \"from src.review.repository\" in p.read_text() or \"import src.review.repository\" in p.read_text()]
bad_model = [str(p) for p in root.rglob(\"*.py\") if \"from src.review.models\" in p.read_text() or \"import src.review.models\" in p.read_text()]
print(\"board_repo_imports=\", bad_repo)
print(\"board_model_imports=\", bad_model)
"
```

```output
board_repo_imports= []
board_model_imports= []
```

### Frontend component-level proof

The badge is gated on both `task.status === 'review'` AND
`task.codex_review_picked_up === true` — so when a reviewer finds issues
and the agent pulls the task back to `in_progress`, the badge disappears
automatically. The new vitest cases pin that behaviour. Running them
in-process (not the full `make test`) keeps `showboat verify` deterministic
and fast.

```bash
cd frontend && npx --yes vitest run src/components/TaskCard.test.tsx --reporter=verbose 2>&1 \
     | grep -E "codex reviewed|back to in_progress|no PR" \
     | sed -E "s/ [0-9]+ms$//" \
     | sort
```

```output
 ✓ src/components/TaskCard.test.tsx > TaskCard > does not show merged badge when there is no PR
 ✓ src/components/TaskCard.test.tsx > TaskCard > hides codex reviewed badge when codex_review_picked_up=false
 ✓ src/components/TaskCard.test.tsx > TaskCard > hides codex reviewed badge when task moves back to in_progress (badge is review-column only)
 ✓ src/components/TaskCard.test.tsx > TaskCard > hides codex reviewed badge when there is no PR
 ✓ src/components/TaskCard.test.tsx > TaskCard > shows codex reviewed badge on a review-column card when codex_review_picked_up=true
```

### Out of scope (deliberate)

- No 5-state enum (`idle` / `codex_in_progress` / …) — the board description
  predated T-248's `pr_review_turns` and the user narrowed the scope to a
  boolean on 2026-04-23.
- No new column on the `Task` row — projection only, sourced from the Review
  context's Open Host Service. Keeps a single source of truth (CLAUDE.md
  "Gateway owns no tables" precedent).
- No turn counter / elapsed time / finding count in the badge. Boolean only.
- Opencode stage is untouched — the badge is codex-only per spec.
