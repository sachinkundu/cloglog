#!/usr/bin/env bash
# Demo for T-260: Visual indication on task card when codex picks up a PR for review.
#
# Scope (per user clarification 2026-04-23): a single boolean badge on review-column
# cards — parallel to the existing PR# + "Merged" indicators. Field is projected
# read-only from `pr_review_turns` via the Review context's Open Host Service
# factory. No new column on the Task row.
#
# Verify-safe: all exec blocks are deterministic file-level booleans, an
# in-process python round-trip (not pytest — see CLAUDE.md re: conftest's
# session-autouse Postgres fixture colliding with `uvx showboat verify`), and
# a frontend vitest run scoped to TaskCard.test.tsx. No live-service calls;
# no repo-wide counts.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
# Top-level demo.md — `scripts/check-demo.sh` (the `make demo-check` step of
# `make quality`) looks for `docs/demos/<branch-or-feature>/demo.md`, not a
# nested sub-directory, so the script writes to the branch root.
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

# `showboat init` refuses to overwrite — delete first so the script is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Task cards in the review column show a 'codex reviewed' badge the moment codex engages with the PR — projected read-only from \`pr_review_turns\` via the Review context's Open Host Service factory."

# ===================================================================
uvx showboat note "$DEMO_FILE" "### T-260 acceptance evidence — file-level booleans

User clarification 2026-04-23 narrowed the task to a single boolean badge
on review-column cards. These booleans are per-file pins of the exact
named file the spec expected the change to land in — no repo-wide counts
(per CLAUDE.md \"Prove with OK/FAIL booleans\")."

# ----- Projection field on TaskCard (NOT on TaskResponse) -----
# Field must be on TaskCard (the board-read shape), NOT on TaskResponse
# (the write-back shape — adding it there would expose a writable column
# that must never be written, violating the read-only projection rule).
# Uses stdlib-only awk to extract each class block, so `showboat verify`
# does not need the uv venv for this check.
uvx showboat exec "$DEMO_FILE" bash \
  'S=src/board/schemas.py
   grep -q "codex_review_picked_up: bool" "$S" && echo "taskcard_has_field=yes" || echo "taskcard_has_field=MISSING"
   awk "/^class TaskResponse/{flag=1; next} /^class [A-Z]/{flag=0} flag" "$S" > /tmp/t260_resp.py
   awk "/^class TaskCard/{flag=1; next} /^class [A-Z]/{flag=0} flag" "$S" > /tmp/t260_card.py
   grep -q "codex_review_picked_up" /tmp/t260_card.py \
     && echo "on_TaskCard=yes" || echo "on_TaskCard=MISSING"
   grep -q "codex_review_picked_up" /tmp/t260_resp.py \
     && echo "on_TaskResponse=LEAK" || echo "on_TaskResponse=no (correct)"'

# ----- Review context exposes the batched projection method on the Protocol -----
uvx showboat exec "$DEMO_FILE" bash \
  'I=src/review/interfaces.py
   R=src/review/repository.py
   grep -q "async def codex_touched_pr_urls" "$I" && echo "interface_has_method=yes" || echo "interface_has_method=MISSING"
   grep -q "async def codex_touched_pr_urls" "$R" && echo "repository_implements_method=yes" || echo "repository_implements_method=MISSING"
   grep -q "PrReviewTurn.stage == \"codex\"" "$R" && echo "repository_filters_stage_codex=yes" || echo "repository_filters_stage_codex=MISSING"'

# ----- DDD: Board imports only the Open Host Service factory, not repository/models -----
uvx showboat exec "$DEMO_FILE" bash \
  'BOARD_DIR=src/board
   grep -rE "from src\\.review\\.(models|repository)" "$BOARD_DIR" > /tmp/t260_boundary.out 2>&1 || true
   if [ -s /tmp/t260_boundary.out ]; then
     echo "board_imports_review_internals=LEAK"; cat /tmp/t260_boundary.out
   else
     echo "board_imports_review_internals=no (correct)"
   fi
   grep -q "from src.review.services import make_review_turn_registry" src/board/routes.py \
     && echo "board_uses_ohs_factory=yes" || echo "board_uses_ohs_factory=MISSING"'

# ----- SSE event type added to the shared EventType enum -----
uvx showboat exec "$DEMO_FILE" bash \
  'E=src/shared/events.py
   grep -q "REVIEW_CODEX_TURN_STARTED" "$E" && echo "event_type_defined=yes" || echo "event_type_defined=MISSING"
   grep -q "review_codex_turn_started" "$E" && echo "event_type_string_value=yes" || echo "event_type_string_value=MISSING"'

# ----- ReviewLoop emits the event on codex turns and NOT on opencode turns -----
uvx showboat exec "$DEMO_FILE" bash \
  'L=src/gateway/review_loop.py
   grep -q "if self._stage == \"codex\":" "$L" && echo "emit_gated_on_codex_stage=yes" || echo "emit_gated_on_codex_stage=MISSING"
   grep -q "EventType.REVIEW_CODEX_TURN_STARTED" "$L" && echo "emit_uses_new_event=yes" || echo "emit_uses_new_event=MISSING"
   grep -q "await event_bus.publish" "$L" && echo "emit_on_event_bus=yes" || echo "emit_on_event_bus=MISSING"'

# ----- Contract (OpenAPI) carries the new field on TaskCard -----
# Using grep rather than a python YAML parser because (a) the system python3
# has no PyYAML (same root cause as the hook rule in CLAUDE.md) and (b)
# `showboat verify` runs without the uv venv. The field needs to land inside
# the TaskCard schema block, not anywhere else in the file — awk extracts
# the block boundary to ssert that specifically.
uvx showboat exec "$DEMO_FILE" bash \
  'Y=docs/contracts/baseline.openapi.yaml
   awk "/^    TaskCard:/{flag=1; next} /^    [A-Z]/{flag=0} flag" "$Y" > /tmp/t260_taskcard_block.yaml
   grep -q "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml \
     && echo "contract_has_field_on_TaskCard=yes" || echo "contract_has_field_on_TaskCard=MISSING"
   grep -A1 "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml | grep -q "type: boolean" \
     && echo "contract_field_is_boolean=yes" || echo "contract_field_is_boolean=MISSING"
   grep -A3 "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml | grep -q "default: false" \
     && echo "contract_field_defaults_false=yes" || echo "contract_field_defaults_false=MISSING"'

# ----- Generated frontend types carry the new field -----
uvx showboat exec "$DEMO_FILE" bash \
  'G=frontend/src/api/generated-types.ts
   grep -q "codex_review_picked_up: boolean" "$G" && echo "generated_types_field=yes" || echo "generated_types_field=MISSING"'

# ----- TaskCard React component renders the badge, gated on status === "review" -----
uvx showboat exec "$DEMO_FILE" bash \
  'T=frontend/src/components/TaskCard.tsx
   P=frontend/src/components/PrLink.tsx
   grep -q "codexReviewed=" "$T" && echo "tsx_wires_badge_prop=yes" || echo "tsx_wires_badge_prop=MISSING"
   grep -q "task.status === .review." "$T" && echo "tsx_gates_on_review_column=yes" || echo "tsx_gates_on_review_column=MISSING"
   grep -q "pr-codex-badge" "$P" && echo "prlink_has_codex_class=yes" || echo "prlink_has_codex_class=MISSING"
   grep -q "codex reviewed" "$P" && echo "prlink_renders_label=yes" || echo "prlink_renders_label=MISSING"'

# ----- Frontend SSE hook subscribes to the new event type (otherwise the
# EventSource listener never fires and the badge wouldn't appear live) -----
uvx showboat exec "$DEMO_FILE" bash \
  'H=frontend/src/hooks/useSSE.ts
   grep -q "review_codex_turn_started" "$H" && echo "sse_hook_subscribes=yes" || echo "sse_hook_subscribes=MISSING"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### In-process projection round-trip

The round-trip below constructs the projection object directly (no DB), flipping
the codex-touched set on and off to prove the card field tracks it. This is
the verify-safe equivalent of the real-DB test at
\`tests/board/test_codex_review_projection.py\` (which runs under \`make test\`
but not under \`uvx showboat verify\` because it needs Postgres)."

# ----- In-process: TaskCard projection tracks codex_touched set -----
# `uv run python` is already used by the T-248 demo (docs/demos/wt-f47-
# two-stage-review/T-248/demo-script.sh) — verify-safe because the uv venv
# is present in local dev and CI, and the command is fully deterministic
# (no network, no subprocess, no DB).
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
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
"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### DDD boundary pin test (structural)

The Board context now talks to Review only via the Open Host Service factory.
A pin test mirrors the existing Gateway→Review guard at
\`tests/gateway/test_review_engine_t248.py\` for the Board→Review edge. Below
is the same check run directly against the filesystem so \`showboat verify\`
can reproduce it byte-exactly."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run python -c "
import pathlib
root = pathlib.Path(\"src/board\")
bad_repo = [str(p) for p in root.rglob(\"*.py\") if \"from src.review.repository\" in p.read_text() or \"import src.review.repository\" in p.read_text()]
bad_model = [str(p) for p in root.rglob(\"*.py\") if \"from src.review.models\" in p.read_text() or \"import src.review.models\" in p.read_text()]
print(\"board_repo_imports=\", bad_repo)
print(\"board_model_imports=\", bad_model)
"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Frontend component-level proof

The badge is gated on both \`task.status === 'review'\` AND
\`task.codex_review_picked_up === true\` — so when a reviewer finds issues
and the agent pulls the task back to \`in_progress\`, the badge disappears
automatically. The new vitest cases pin that behaviour. Running them
in-process (not the full \`make test\`) keeps \`showboat verify\` deterministic
and fast."

# Vitest output includes per-test timings (e.g. "2ms") that vary between
# runs. `showboat verify` is byte-exact, so strip the timing suffix before
# capture — match `\d+ms` at end-of-line.
uvx showboat exec "$DEMO_FILE" bash \
  'cd frontend && npx --yes vitest run src/components/TaskCard.test.tsx --reporter=verbose 2>&1 \
     | grep -E "codex reviewed|back to in_progress|no PR" \
     | sed -E "s/ [0-9]+ms$//" \
     | sort'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Out of scope (deliberate)

- No 5-state enum (\`idle\` / \`codex_in_progress\` / …) — the board description
  predated T-248's \`pr_review_turns\` and the user narrowed the scope to a
  boolean on 2026-04-23.
- No new column on the \`Task\` row — projection only, sourced from the Review
  context's Open Host Service. Keeps a single source of truth (CLAUDE.md
  \"Gateway owns no tables\" precedent).
- No turn counter / elapsed time / finding count in the badge. Boolean only.
- Opencode stage is untouched — the badge is codex-only per spec."

uvx showboat verify "$DEMO_FILE"
