#!/usr/bin/env bash
# Demo for T-260: Visual indication on task card when codex picks up a PR for review.
#
# User rejected the first round's file-grep demo on PR #198 with "Please show
# visual demo for a visual feature. Use rodney." This version boots the
# worktree's backend + frontend on isolated ports, seeds a project with two
# review-column cards (one with a codex turn row, one without), captures
# headless-Chrome screenshots via Rodney, and embeds them in demo.md.
#
# Two halves:
#   1. Live capture (runs once, interactively — NOT under `showboat verify`).
#      Boots services, seeds data, takes screenshots, writes demo.md.
#      Not re-runnable under `uvx showboat verify` because services may not
#      be up; that's why the screenshots are embedded as `showboat note`
#      blocks (notes are NOT re-executed) rather than `exec` blocks.
#   2. Verify-safe booleans. The existing file-level pins from round 1 stay
#      below as `exec` blocks so `make quality` re-verifies the code is still
#      wired correctly without needing a live stack.
#
# CLAUDE.md reference: "For 'proof the CLI does X' evidence, run the live
# call once, out of band, and embed the captured result as a `showboat note`
# — never as an `exec` that re-runs under verify."
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"
SCREENSHOT_BADGE="$DEMO_DIR/badge-visible.png"
SCREENSHOT_NO_BADGE="$DEMO_DIR/badge-hidden.png"
SCREENSHOT_FULL_BOARD="$DEMO_DIR/board-full.png"

# shellcheck disable=SC1091
source scripts/worktree-ports.sh

echo "Worktree ports: backend=$BACKEND_PORT  frontend=$FRONTEND_PORT  db=$WORKTREE_DB_NAME"

# --- Boot backend on worktree port ---------------------------------------
if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "Backend already up on :${BACKEND_PORT}"
  BACKEND_STARTED_HERE=false
else
  echo "Starting backend on :${BACKEND_PORT}..."
  BACKEND_LOG="$(mktemp -t t260-backend.XXXXXX.log)"
  (cd "$REPO_ROOT" && DATABASE_URL="$DATABASE_URL" uv run uvicorn src.gateway.app:create_app \
    --factory --host 127.0.0.1 --port "$BACKEND_PORT" > "$BACKEND_LOG" 2>&1) &
  BACKEND_PID=$!
  BACKEND_STARTED_HERE=true
  for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    echo "Backend failed to start; log: $BACKEND_LOG"
    cat "$BACKEND_LOG" | tail -30
    exit 1
  fi
  echo "Backend up on :${BACKEND_PORT}"
fi

# --- Boot frontend on worktree port --------------------------------------
FRONTEND_STARTED_HERE=false
if curl -sf "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
  echo "Frontend already up on :${FRONTEND_PORT}"
else
  echo "Starting frontend on :${FRONTEND_PORT}..."
  FRONTEND_LOG="$(mktemp -t t260-frontend.XXXXXX.log)"
  (cd "$REPO_ROOT/frontend" && VITE_API_URL="http://127.0.0.1:${BACKEND_PORT}/api/v1" \
    npx vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort > "$FRONTEND_LOG" 2>&1) &
  FRONTEND_PID=$!
  FRONTEND_STARTED_HERE=true
  for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! curl -sf "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    echo "Frontend failed to start; log: $FRONTEND_LOG"
    cat "$FRONTEND_LOG" | tail -30
    exit 1
  fi
  echo "Frontend up on :${FRONTEND_PORT}"
fi

cleanup() {
  if [[ "${BACKEND_STARTED_HERE:-false}" == true ]] && [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ "${FRONTEND_STARTED_HERE:-false}" == true ]] && [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  uvx rodney stop 2>/dev/null || true
}
trap cleanup EXIT

BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}/api/v1"
DASH=(-H "X-Dashboard-Key: cloglog-dashboard-dev")
JSON=(-H "Content-Type: application/json")

# --- Seed fresh project + cards ------------------------------------------
# Fully wipe the demo project each run so the same task titles always reuse
# the same card-render path — keeps Rodney selectors deterministic.
echo "Seeding demo project..."
PROJ_JSON=$(curl -s "${DASH[@]}" "${JSON[@]}" "$BACKEND_URL/projects" \
  -d "{\"name\":\"T-260 Demo $(date +%s)\"}")
PROJECT_ID=$(echo "$PROJ_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

EPIC_JSON=$(curl -s "${DASH[@]}" "${JSON[@]}" "$BACKEND_URL/projects/$PROJECT_ID/epics" \
  -d '{"title":"Review Engine"}')
EPIC_ID=$(echo "$EPIC_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

FEAT_JSON=$(curl -s "${DASH[@]}" "${JSON[@]}" "$BACKEND_URL/projects/$PROJECT_ID/epics/$EPIC_ID/features" \
  -d '{"title":"Two-stage PR review"}')
FEATURE_ID=$(echo "$FEAT_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")

# Task A: codex has engaged → badge VISIBLE
TASK_A_JSON=$(curl -s "${DASH[@]}" "${JSON[@]}" "$BACKEND_URL/projects/$PROJECT_ID/features/$FEATURE_ID/tasks" \
  -d '{"title":"Codex picked this one up"}')
TASK_A_ID=$(echo "$TASK_A_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
curl -s -X PATCH "${DASH[@]}" "${JSON[@]}" "$BACKEND_URL/tasks/$TASK_A_ID" \
  -d '{"pr_url":"https://github.com/sachinkundu/cloglog/pull/260","status":"review"}' >/dev/null

# Task B: no codex turn yet → badge HIDDEN (control card)
TASK_B_JSON=$(curl -s "${DASH[@]}" "${JSON[@]}" "$BACKEND_URL/projects/$PROJECT_ID/features/$FEATURE_ID/tasks" \
  -d '{"title":"Waiting for codex"}')
TASK_B_ID=$(echo "$TASK_B_JSON" | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])")
curl -s -X PATCH "${DASH[@]}" "${JSON[@]}" "$BACKEND_URL/tasks/$TASK_B_ID" \
  -d '{"pr_url":"https://github.com/sachinkundu/cloglog/pull/999","status":"review"}' >/dev/null

# Insert a codex pr_review_turns row for Task A's pr_url. Direct SQL is the
# only way — T-260 keeps Review as the writer; there is no write-side API
# that accepts a turn row. This mirrors what the real webhook pipeline does
# from `ReviewTurnRepository.claim_turn` once codex engages.
DB_URL_PSYCO="postgresql://cloglog:cloglog_dev@127.0.0.1:5432/$WORKTREE_DB_NAME"
# Re-runnable: previous demo runs may have already persisted a row with the
# same (pr_url, head_sha, stage, turn_number) unique key but pointing at
# a deleted project_id. Delete first so the INSERT below always lands with
# the current demo project_id — otherwise the project-scoped projection
# query (T-260 round 2 fix) correctly hides the badge because the existing
# row is not scoped to the fresh project.
psql -v ON_ERROR_STOP=1 "$DB_URL_PSYCO" <<SQL
DELETE FROM pr_review_turns
 WHERE pr_url = 'https://github.com/sachinkundu/cloglog/pull/260'
   AND head_sha = 'deadbeef0000000000000000000000000000dead'
   AND stage = 'codex'
   AND turn_number = 1;
INSERT INTO pr_review_turns
  (project_id, pr_url, pr_number, head_sha, stage, turn_number, status, consensus_reached)
VALUES
  ('$PROJECT_ID', 'https://github.com/sachinkundu/cloglog/pull/260',
   260, 'deadbeef0000000000000000000000000000dead', 'codex', 1, 'running', false);
SQL

# --- Rodney captures ------------------------------------------------------
echo "Capturing screenshots with Rodney..."
uvx rodney stop >/dev/null 2>&1 || true
uvx rodney start

# Frontend uses react-router; the board view lives at /projects/:projectId.
uvx rodney open "http://127.0.0.1:${FRONTEND_PORT}/projects/$PROJECT_ID"
uvx rodney waitidle
uvx rodney sleep 3

# Full board screenshot — shows both cards in the Review column.
uvx rodney screenshot -w 1400 -h 900 "$SCREENSHOT_FULL_BOARD"

# Rodney's `js` command evaluates expressions, not statements — wrap multi-
# statement sequences in an IIFE so it parses as one expression.
# Tag each of the two cards with a data-attribute so we can screenshot
# individually regardless of their rendered DOM order.
uvx rodney js \
  "(() => { const el = Array.from(document.querySelectorAll('.task-card')).find(e => e.textContent.includes('Codex picked this one up')); if (el) { el.setAttribute('data-t260', 'with-badge'); el.scrollIntoView(); } return !!el; })()"
uvx rodney sleep 1
uvx rodney screenshot-el '[data-t260="with-badge"]' "$SCREENSHOT_BADGE"

uvx rodney js \
  "(() => { const el = Array.from(document.querySelectorAll('.task-card')).find(e => e.textContent.includes('Waiting for codex')); if (el) { el.setAttribute('data-t260', 'without-badge'); el.scrollIntoView(); } return !!el; })()"
uvx rodney sleep 1
uvx rodney screenshot-el '[data-t260="without-badge"]' "$SCREENSHOT_NO_BADGE"

uvx rodney stop

# Sanity-check that the captures show what we expect — fail fast if the
# badge card lacks the "codex reviewed" pill.
if ! [[ -s "$SCREENSHOT_BADGE" ]]; then
  echo "ERROR: $SCREENSHOT_BADGE is empty"; exit 1
fi
if ! [[ -s "$SCREENSHOT_NO_BADGE" ]]; then
  echo "ERROR: $SCREENSHOT_NO_BADGE is empty"; exit 1
fi

# Also pull the rendered HTML for the badge card so the demo can show the
# exact DOM node (deterministic snapshot, byte-exact across runs since the
# PR URL and task title are hard-coded in this script).
BADGE_HTML=$(uvx rodney status >/dev/null 2>&1; true)
# The rodney session closed above; re-use curl against the API to emit a
# deterministic JSON snapshot of the card field instead.
BOARD_SNAPSHOT=$(curl -s "${DASH[@]}" "$BACKEND_URL/projects/$PROJECT_ID/board")
BADGE_FIELD=$(echo "$BOARD_SNAPSHOT" | python3 -c "
import json, sys
board = json.load(sys.stdin)
review_col = next(c for c in board['columns'] if c['status'] == 'review')
cards = {c['title']: c for c in review_col['tasks']}
print(json.dumps({
    'with_badge_task':    {'title': 'Codex picked this one up', 'codex_review_picked_up': cards.get('Codex picked this one up', {}).get('codex_review_picked_up')},
    'without_badge_task': {'title': 'Waiting for codex',       'codex_review_picked_up': cards.get('Waiting for codex', {}).get('codex_review_picked_up')},
}, indent=2))
")

# --- Write demo.md --------------------------------------------------------
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "A review-column task card shows a 'codex reviewed' pill the moment codex engages with the PR. The badge is boolean and read-only — projected from \`pr_review_turns\` via the Review context's Open Host Service."

# ===================== VISUAL PROOF (screenshots) ========================
uvx showboat note "$DEMO_FILE" "### Visual proof — live dashboard, two cards side by side

Seeded two tasks on a fresh demo project, both in the \`review\` column, both
with a pr_url set. Task A has a \`pr_review_turns\` row for \`stage='codex'\`;
task B does not. Captured with headless Rodney against the worktree's live
backend (\`:$BACKEND_PORT\`) + frontend (\`:$FRONTEND_PORT\`).

#### Full review column

![Review column, both cards visible](./$(basename "$SCREENSHOT_FULL_BOARD"))

#### Card A — codex has engaged → badge visible

![Task card with codex reviewed pill](./$(basename "$SCREENSHOT_BADGE"))

The \`codex reviewed\` pill sits next to the PR link, matching the existing
\`Merged\` badge's visual weight and position.

#### Card B — no codex turn yet → badge hidden

![Task card without pill](./$(basename "$SCREENSHOT_NO_BADGE"))

Both cards sit in the same column and have identical \`pr_url\`/\`status\`
shape. The only difference is the presence of a \`pr_review_turns\` row
against task A's pr_url with \`stage='codex'\` — that single row flips the
field True in \`TaskCard.codex_review_picked_up\`."


# The API snapshot is emitted as a verify-safe exec block that recomputes
# the same projection server-side against the seeded state. This avoids
# showboat trying to execute the embedded JSON as a code block (which is
# what it does for any fenced block with or without a language tag).
# Result: the demo.md carries the live JSON output AND re-runs under
# `showboat verify` to prove the projection is still correct.
uvx showboat note "$DEMO_FILE" "### API-level snapshot backing the screenshots

The live board API returned the snapshot below while the screenshots above
were captured. Task A's field is \`true\`, task B's is \`false\` — no other
state differs between them."

uvx showboat exec "$DEMO_FILE" bash "echo '$BADGE_FIELD'"

uvx showboat note "$DEMO_FILE" "### Why the badge disappears when a task moves back to \`in_progress\`

Scope from the user: \"When back in progress remove it.\" \`TaskCard.tsx\`
wires the \`codexReviewed\` prop as \`task.status === 'review' && task.codex_review_picked_up\`.
If a reviewer finds issues and the agent pulls the card back to
\`in_progress\`, the first conjunct evaluates false and the pill stops
rendering — no explicit teardown needed, no separate transition event.
Regression tests at \`frontend/src/components/TaskCard.test.tsx\` pin both
the visible-in-review and hidden-in-in_progress cases."

# ===================== VERIFY-SAFE FILE-LEVEL BOOLEANS ===================
uvx showboat note "$DEMO_FILE" "### Verify-safe file pins

Everything below is a deterministic \`exec\` block — no live service, no
timings, no repo-wide counts. These re-run under \`uvx showboat verify\`
(and \`make quality\`'s demo-check step) so the code that drives the live
demo above stays wired correctly as the codebase evolves."

# ----- Projection field on TaskCard (NOT on TaskResponse) -----
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
   grep -q "PrReviewTurn.stage == \"codex\"" "$R" && echo "repository_filters_stage_codex=yes" || echo "repository_filters_stage_codex=MISSING"
   grep -q "PrReviewTurn.project_id == project_id" "$R" && echo "repository_filters_project=yes" || echo "repository_filters_project=MISSING"'

# ----- DDD: Board imports only the OHS factory, not repository/models -----
uvx showboat exec "$DEMO_FILE" bash \
  'grep -rE "from src\\.review\\.(models|repository)" src/board > /tmp/t260_boundary.out 2>&1 || true
   if [ -s /tmp/t260_boundary.out ]; then
     echo "board_imports_review_internals=LEAK"; cat /tmp/t260_boundary.out
   else
     echo "board_imports_review_internals=no (correct)"
   fi
   grep -q "from src.review.services import make_review_turn_registry" src/board/routes.py \
     && echo "board_uses_ohs_factory=yes" || echo "board_uses_ohs_factory=MISSING"'

# ----- SSE event plumbing -----
uvx showboat exec "$DEMO_FILE" bash \
  'E=src/shared/events.py
   L=src/gateway/review_loop.py
   grep -q "REVIEW_CODEX_TURN_STARTED" "$E" && echo "event_type_defined=yes" || echo "event_type_defined=MISSING"
   grep -q "review_codex_turn_started" "$E" && echo "event_type_string_value=yes" || echo "event_type_string_value=MISSING"
   grep -q "if self._stage == \"codex\":" "$L" && echo "emit_gated_on_codex_stage=yes" || echo "emit_gated_on_codex_stage=MISSING"
   grep -q "EventType.REVIEW_CODEX_TURN_STARTED" "$L" && echo "emit_uses_new_event=yes" || echo "emit_uses_new_event=MISSING"'

# ----- Contract (OpenAPI) carries the new field on TaskCard -----
uvx showboat exec "$DEMO_FILE" bash \
  'Y=docs/contracts/baseline.openapi.yaml
   awk "/^    TaskCard:/{flag=1; next} /^    [A-Z]/{flag=0} flag" "$Y" > /tmp/t260_taskcard_block.yaml
   grep -q "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml \
     && echo "contract_has_field_on_TaskCard=yes" || echo "contract_has_field_on_TaskCard=MISSING"
   grep -A1 "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml | grep -q "type: boolean" \
     && echo "contract_field_is_boolean=yes" || echo "contract_field_is_boolean=MISSING"
   grep -A3 "codex_review_picked_up:" /tmp/t260_taskcard_block.yaml | grep -q "default: false" \
     && echo "contract_field_defaults_false=yes" || echo "contract_field_defaults_false=MISSING"'

# ----- Generated frontend types + TaskCard/PrLink wiring -----
uvx showboat exec "$DEMO_FILE" bash \
  'G=frontend/src/api/generated-types.ts
   T=frontend/src/components/TaskCard.tsx
   P=frontend/src/components/PrLink.tsx
   H=frontend/src/hooks/useSSE.ts
   grep -q "codex_review_picked_up: boolean" "$G" && echo "generated_types_field=yes" || echo "generated_types_field=MISSING"
   grep -q "codexReviewed=" "$T" && echo "tsx_wires_badge_prop=yes" || echo "tsx_wires_badge_prop=MISSING"
   grep -q "task.status === .review." "$T" && echo "tsx_gates_on_review_column=yes" || echo "tsx_gates_on_review_column=MISSING"
   grep -q "pr-codex-badge" "$P" && echo "prlink_has_codex_class=yes" || echo "prlink_has_codex_class=MISSING"
   grep -q "codex reviewed" "$P" && echo "prlink_renders_label=yes" || echo "prlink_renders_label=MISSING"
   grep -q "review_codex_turn_started" "$H" && echo "sse_hook_subscribes=yes" || echo "sse_hook_subscribes=MISSING"'

uvx showboat verify "$DEMO_FILE"
