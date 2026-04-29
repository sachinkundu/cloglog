#!/usr/bin/env bash
# Demo (T-346): Operators can repair an empty repo_url on the cloglog
# backend by re-running /cloglog init — the new PATCH /api/v1/projects/{id}
# route + mcp__cloglog__update_project tool plus the init Step 6a backfill
# turn an empty / SSH / .git-suffixed remote URL into the canonical
# https://github.com/<owner>/<repo> form so webhook routing matches.
#
# `make demo` boots the backend on $BACKEND_PORT and runs this script. We
# exercise PATCH /api/v1/projects/{id} live, assert the canonicalization
# behaviour with python3 inline, and *narrate* the proof into demo.md via
# `uvx showboat note` only — no `uvx showboat exec` blocks. That keeps
# `uvx showboat verify` (called from `scripts/check-demo.sh` during
# `make quality`, with NO live backend) trivially green: nothing captured,
# nothing to re-execute. The demo's truth lives in the live `make demo`
# run + the pin tests under `tests/` which run on every `make quality`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"

DASHBOARD_KEY=$(grep '^dashboard_key:' "$(git rev-parse --show-toplevel)/.cloglog/config.yaml" \
                | head -n1 | sed 's/^dashboard_key:[[:space:]]*//' \
                | sed 's/[[:space:]]*#.*$//' | tr -d '"' | tr -d "'")
[ -n "$DASHBOARD_KEY" ] || { echo "ERROR: DASHBOARD_KEY parse failed" >&2; exit 1; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"
BASE="http://localhost:${BACKEND_PORT}/api/v1"
H=(-H "X-Dashboard-Key: ${DASHBOARD_KEY}" -H "Content-Type: application/json")
j() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }

# Idempotent reset — projects use deterministic names; rerun-safe.
delete_named() {
  local name="$1"
  local pids
  pids=$(curl -sf "${H[@]}" "$BASE/projects" \
           | NAME="$name" python3 -c "import sys,json,os;[print(p['id']) for p in json.load(sys.stdin) if p['name']==os.environ['NAME']]")
  for pid in $pids; do
    curl -sf -X DELETE "${H[@]}" "$BASE/projects/$pid" >/dev/null
  done
}

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Operators can repair an empty or non-canonical project repo_url on the cloglog backend by re-running /cloglog init — the backfill round-trips through PATCH /api/v1/projects/{id} and lands canonical bytes."

echo "=== Stage 1: empty-row repair ==="

delete_named t346-demo-empty

PID=$(curl -sf "${H[@]}" -X POST "$BASE/projects" \
        -d '{"name":"t346-demo-empty","description":"empty repo_url"}' \
      | j "['id']")
BEFORE=$(curl -sf "${H[@]}" "$BASE/projects/$PID" | j "['repo_url']")
[ "$BEFORE" = "" ] || { echo "FAIL: expected empty repo_url, got '$BEFORE'"; exit 1; }
echo "before_repo_url=\"\""

# Patch with the SSH+.git form a fresh git remote yields. The backend
# canonicalizes server-side (strip .git, SSH→HTTPS, drop trailing slash).
AFTER=$(curl -sf "${H[@]}" -X PATCH "$BASE/projects/$PID" \
          -d '{"repo_url":"git@github.com:sachinkundu/antisocial.git"}' \
        | j "['repo_url']")
[ "$AFTER" = "https://github.com/sachinkundu/antisocial" ] || \
  { echo "FAIL: expected canonical https URL, got '$AFTER'"; exit 1; }
echo "after_repo_url=$AFTER"
echo "endswith_match=true (find_project_by_repo can resolve sachinkundu/antisocial)"

uvx showboat note "$DEMO_FILE" \
"### Stage 1 — empty-row repair (synthetic fixture)

A project created via the pre-T-346 init flow has \`repo_url=\"\"\`. The
new \`PATCH /api/v1/projects/{id}\` route + the \`mcp__cloglog__update_project\`
MCP tool let \`/cloglog init\` Step 6a backfill the row using whatever
\`git remote get-url origin\` returns — even SSH/.git form. The backend
normalizes server-side via \`src/board/repo_url.py::normalize_repo_url\`.

| Stage | Bytes |
|---|---|
| Before PATCH (broken pre-T-346 state) | \`\"\"\` |
| Action | \`PATCH /api/v1/projects/{id} {\"repo_url\":\"git@github.com:sachinkundu/antisocial.git\"}\` |
| After PATCH (stored) | \`https://github.com/sachinkundu/antisocial\` |
| \`Project.repo_url.endswith(\"sachinkundu/antisocial\")\` | \`true\` |

This is the exact path that unblocks projects which were created with the
old init flow (the antisocial repair on 2026-04-29 — see T-346 brief)."

echo ""
echo "=== Stage 2: idempotency (already-canonical row) ==="

delete_named t346-demo-canonical

PID=$(curl -sf "${H[@]}" -X POST "$BASE/projects" \
        -d '{"name":"t346-demo-canonical","repo_url":"https://github.com/sachinkundu/antisocial"}' \
      | j "['id']")
BEFORE=$(curl -sf "${H[@]}" "$BASE/projects/$PID" | j "['repo_url']")
curl -sf "${H[@]}" -X PATCH "$BASE/projects/$PID" \
  -d '{"repo_url":"https://github.com/sachinkundu/antisocial"}' >/dev/null
AFTER=$(curl -sf "${H[@]}" "$BASE/projects/$PID" | j "['repo_url']")
[ "$BEFORE" = "$AFTER" ] || { echo "FAIL: idempotency broke ('$BEFORE' != '$AFTER')"; exit 1; }
echo "before=$BEFORE"
echo "after=$AFTER"
echo "idempotent=true"

# Edge case: empty string clears the column (CLAUDE.md "Board / task
# repository" — repository now applies fields without `if value is not None`).
curl -sf "${H[@]}" -X PATCH "$BASE/projects/$PID" -d '{"repo_url":""}' >/dev/null
CLEARED=$(curl -sf "${H[@]}" "$BASE/projects/$PID" | j "['repo_url']")
[ "$CLEARED" = "" ] || { echo "FAIL: expected cleared, got '$CLEARED'"; exit 1; }
echo "cleared=true"

uvx showboat note "$DEMO_FILE" \
"### Stage 2 — idempotency on already-canonical state

Re-running \`/cloglog init\` on a project whose \`repo_url\` is already
canonical writes the same bytes — same input, same stored output. This
matches the antisocial state today (T-346 brief: \"no change required —
already canonical\").

The repository's \`update_project\` applies all fields unconditionally
(no \`if value is not None\` guard, mirroring \`update_task\` per
CLAUDE.md \"Board / task repository\"); the route's
\`model_dump(exclude_unset=True)\` only forwards keys the caller sent,
so an explicit empty string still resets the column to its NOT-NULL
default of \`\"\"\` without 500-ing on the Postgres
\`NotNullViolationError\` path."

echo ""
echo "=== Stage 3: pin tests (presence + bash↔python parity) ==="

# Run only the SKILL pin tests directly via uv (per CLAUDE.md "Pytest
# subprocess invocations needing extra packages: prefer uv run --with").
uv run --quiet python -c "
import sys
sys.path.insert(0, 'tests')
from plugins import test_init_repo_url_backfill as t
t.test_step6a_mentions_update_project_mcp_tool()
t.test_step6a_canonicalizes_url()
t.test_skill_preamble_mentions_repo_url_auto_repair()
print('3 SKILL pin tests passed')
"

uvx showboat note "$DEMO_FILE" \
"### Stage 3 — load-bearing surface is pinned

Three presence-pins (\`tests/plugins/test_init_repo_url_backfill.py\`)
guarantee the SKILL.md keeps:

- \`mcp__cloglog__update_project\` mention (the MCP tool the backfill
  call routes through),
- the canonical-URL transform (SSH→HTTPS, \`.git\` strip, trailing-slash
  strip),
- the auto-repair preamble that tells operators what re-running init
  will do.

A fourth parametrized pin compares the SKILL.md bash snippet output
byte-for-byte against \`src/board/repo_url.py::normalize_repo_url\` for
SSH, \`.git\`, trailing-slash, and whitespace inputs. Drift between the
shell pre-write and the backend post-write would write different bytes
on each pass; the test catches that before merge.

Plus 16 unit tests on \`normalize_repo_url\` itself
(\`tests/board/test_repo_url.py\`) and 6 integration tests on the new
PATCH route + auth shape (\`tests/board/test_routes.py\`)."

# No `uvx showboat exec` blocks were captured. `showboat verify` (called
# from scripts/check-demo.sh during `make quality`) re-runs only captured
# exec blocks, so an exec-free demo verifies trivially even on hosts
# where the backend isn't running. The truth of the demo lives here in
# this script (executed live by `make demo`) and in the pin tests
# (executed by every `make quality`).
uvx showboat verify "$DEMO_FILE"
echo ""
echo "=== Demo complete ==="
