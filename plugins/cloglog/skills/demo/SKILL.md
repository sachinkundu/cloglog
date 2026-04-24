---
name: demo
description: Proof-of-work demo with Showboat and Rodney — invoked before every PR
user-invocable: false
---

# Proof-of-Work Demo

Stop and ask: **what would I show on demo day?**

This skill walks you through deciding whether a demo is needed, and — when
it is — producing one that proves the feature works from the stakeholder's
perspective, not the engineer's.

The flow has three possible terminal states for a PR:

1. **Auto-exempt** (Step 0) — every changed file is developer-tooling
   infrastructure, covered by the static allowlist. No artifact produced.
2. **Exempt via `exemption.md`** (Step 1) — the `demo-classifier` subagent
   reads the diff and verdict's `no_demo`. The skill writes
   `docs/demos/<branch>/exemption.md` with a hash of the diff.
3. **Real demo** (Steps 2–6) — the classifier says `needs_demo`, or you
   already know the change is user-observable. Produce a Showboat/Rodney
   demo.

Which state applies is not your judgment call to make on gut feel. Run
Step 0. Run Step 1 if Step 0 doesn't terminate. Only write a real demo
when the flow directs you to.

---

## Step 0 — Static fast-path

Check whether every changed file is developer infrastructure. If so, the
gate auto-exempts and you write nothing.

```bash
BASE=$(git merge-base origin/main HEAD 2>/dev/null || git merge-base main HEAD)
CHANGED=$(git diff --name-only "$BASE" HEAD)
NONALLOWLIST=$(echo "$CHANGED" | grep -vE '^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|^tests/|^Makefile$|^plugins/[^/]+/(hooks|skills|agents|templates)/|^pyproject\.toml$|^ruff\.toml$|package-lock\.json$|\.lock$' || true)

if [[ -z "$NONALLOWLIST" ]]; then
  echo "Auto-exempt: all changes are in the static allowlist."
  # Skill exits here. No file written. scripts/check-demo.sh will reach
  # the same conclusion with the same regex when `make quality` runs.
  exit 0
fi
```

The regex **must** be kept bit-identical to the one in
`scripts/check-demo.sh`. Drift between the two silently re-introduces
the F-51 failure mode the skill was written to prevent — agents
producing synthetic grep/awk demos to satisfy a gate that didn't need
satisfying. If you edit one, edit both, and re-run
`tests/test_check_demo_allowlist.py`.

---

## Step 1 — Classifier (only runs if Step 0 did not auto-exempt)

First, resolve the merge-base SHA using the **same fallback chain as
Step 0 and `scripts/check-demo.sh`** — never hard-code `origin/main`.
Worktrees that have only local `main` configured must still be able to
classify:

```bash
MERGE_BASE=$(git merge-base origin/main HEAD 2>/dev/null \
  || git merge-base main HEAD 2>/dev/null \
  || echo main)
```

Then spawn the `demo-classifier` subagent via the `Agent` tool, passing
`MERGE_BASE` explicitly so the subagent doesn't re-resolve (and so its
`diff_hash` is computed against the exact same ref the gate will
recompute against):

```
Agent(
  description: "Classify demo need for current diff",
  subagent_type: "demo-classifier",
  prompt: "BASE=<the MERGE_BASE you resolved above, literal SHA>. Read git diff \"$BASE\" HEAD and git diff --name-only \"$BASE\" HEAD, then emit the JSON verdict per your subagent definition. Do not write any files. No prose — JSON only."
)
```

Using a resolved SHA (rather than `origin/main`) makes the command
bit-identical to what `scripts/check-demo.sh` runs at gate time:
`git diff $MERGE_BASE HEAD | sha256sum`. The three-dot and two-dot
forms yield the same bytes when `$BASE` is already the merge-base.

The subagent emits exactly one JSON object on stdout:

```json
{
  "verdict": "needs_demo" | "no_demo",
  "reasoning": "signal/counter-signal + counterfactual",
  "diff_hash": "<sha256 of git diff origin/main...HEAD>",
  "suggested_demo_shape": "backend-curl" | "frontend-screenshot" | "mcp-tool-exec" | "cli-exec" | null
}
```

Parse the JSON mechanically. Ignore anything that is not valid JSON —
treat it as a classifier failure and escalate rather than guess.

### If `verdict == "no_demo"`

Write `docs/demos/<branch>/exemption.md` and commit it. Branch-name
slashes become hyphens (`feat/foo` → `feat-foo`). Frontmatter must
carry `verdict`, `diff_hash`, `classifier`, `generated_at` — those four
fields are what `scripts/check-demo.sh` reads.

```bash
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
mkdir -p "$DEMO_DIR"

cat > "$DEMO_DIR/exemption.md" <<MD
---
verdict: no_demo
diff_hash: <classifier's diff_hash, verbatim>
classifier: demo-classifier
generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## Why no demo

<paste classifier reasoning verbatim — signal, counter-signal, counterfactual>

## Changed files

$(git diff --name-only "$MERGE_BASE" HEAD | sed 's/^/- /')
MD
```

Then:
- `git add "$DEMO_DIR/exemption.md"` and commit it alongside your code
  changes.
- Skill exits. Your PR body uses the compact exemption section shown
  in Step 6 below.
- `scripts/check-demo.sh` recomputes the hash at gate time; if you keep
  coding after exemption, the hash drifts and the gate fails. That is
  intentional — re-run this skill to reclassify.

### If `verdict == "needs_demo"`

Proceed to Step 2 below. Seed the decision table with the classifier's
`suggested_demo_shape` as a starting point:

- `backend-curl` → Backend API / CLI row.
- `frontend-screenshot` → Frontend / UI row.
- `mcp-tool-exec` → MCP server tool row.
- `cli-exec` → CLI row (subset of backend/API).

The classifier is a suggestion, not a decree — if the diff is a
combo (backend + frontend), Step 3 tells you to run both.

---

## Step 2 — State the feature

Write one sentence from the stakeholder's view. This sentence opens your `demo.md` and your PR body.

**Good:** "Users can now drag tasks between Kanban columns and the order persists on refresh."
**Bad:** "I added a PATCH /tasks/{id}/position endpoint and updated the frontend drag handler."

The stakeholder sentence describes what the user can now *do*, not what you built.

---

## Step 3 — Demo decision table

Pick your row based on what changed:

| What changed | What to show | Capture method |
|---|---|---|
| Backend API / CLI | curl requests showing before → after state | Showboat `exec` + `note` |
| Frontend / UI | Browser screenshots of state transitions | Rodney screenshots → Showboat `image` |
| MCP server tool | curl the backend endpoint AND a Claude session calling the actual MCP tool | Showboat `exec` + `note` |
| Backend + Frontend combo | API curl for the write path + Rodney screenshots for the read path | Both Showboat flows combined |
| Docs / config only | Should have auto-exempted at Step 0. If you're here, Step 0 or Step 1 made a mistake — halt and re-check. | N/A |

If your change touches code (any `.py`, `.ts`, `.tsx`, `.js` file) AND the classifier returned `needs_demo`, you need a demo. Test output, log lines, and migration output are **not** demos — they are test evidence. The demo shows a user action and its outcome.

---

## Step 4 — Show the journey

A demo has three moments:

1. **Before** — the state before the user acts (e.g., empty list, old value, missing row)
2. **Action** — what the user does (e.g., POST /projects, drag task, call MCP tool)
3. **After** — the new state that proves the feature worked (e.g., project appears, task in new column, tool returns expected data)

Not just the happy path — include at least one edge case or error response that shows the guard rails work.

---

## Step 5 — Produce the demo

### Two-file structure

Every demo has two files under `docs/demos/<branch-name>/`:

- **`demo-script.sh`** — the script `make demo` executes. Contains your Showboat/Rodney commands. `make demo` starts the backend (and frontend if needed), then calls this script.
- **`demo.md`** — the Showboat output document. Generated by `uvx showboat init` and populated by `uvx showboat note`/`exec`/`image`. This is what goes in the PR.

The branch name is the demo directory name. Branch `wt-f45-agent-demo-impl` → `docs/demos/wt-f45-agent-demo-impl/`.

### Backend / API / CLI demo

Write `docs/demos/<branch>/demo-script.sh`:

```bash
#!/usr/bin/env bash
# Demo: <feature description>
# Called by make demo (server + DB already running).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"  # sets $BACKEND_PORT, $FRONTEND_PORT, $DATABASE_URL

# Normalize slashes in branch names — scripts/check-demo.sh maps feat/foo → feat-foo.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"
BASE="http://localhost:${BACKEND_PORT}/api/v1"

# `uvx showboat init` refuses to overwrite — delete the file so `make demo` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" "<stakeholder sentence here>"

# Show the before state
uvx showboat note "$DEMO_FILE" "Before: no projects exist"
uvx showboat exec "$DEMO_FILE" \
  'curl -sf "$BASE/projects" -H "X-Dashboard-Key: cloglog-dashboard-dev"'

# Perform the action
uvx showboat note "$DEMO_FILE" "Action: create a project"
uvx showboat exec "$DEMO_FILE" \
  'curl -sf -X POST "$BASE/projects" \
    -H "X-Dashboard-Key: cloglog-dashboard-dev" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"demo-project\"}"'

# Show the after state
uvx showboat note "$DEMO_FILE" "After: project appears in list"
uvx showboat exec "$DEMO_FILE" \
  'curl -sf "$BASE/projects" -H "X-Dashboard-Key: cloglog-dashboard-dev"'

uvx showboat verify "$DEMO_FILE"
```

**`exec` quoting — it's argv, not a shell.** Showboat's form is `uvx showboat exec <file> <interpreter> [code]`. A single command + args works if the interpreter is shell-aware:

```bash
uvx showboat exec "$DEMO_FILE" \
  'curl -sf "$BASE/projects" -H "X-Dashboard-Key: cloglog-dashboard-dev"'
```

When you need pipes, `$(...)` substitution, redirects, or `&&`, pass the interpreter explicitly as a SECOND positional and the code as the THIRD — do NOT use `bash -c`:

```bash
# CORRECT — two positionals: interpreter, then shell code
uvx showboat exec "$DEMO_FILE" bash 'curl -sf "$BASE/health" | jq -r .status'

# WRONG — showboat passes "-c" as the code and bash fails with "option requires an argument"
uvx showboat exec "$DEMO_FILE" bash -c 'curl -sf "$BASE/health"'
```

The `bash "<code>"` two-positional form is the canonical way to run shell inside an `exec` block.

**Do NOT call `uv run pytest` inside an `exec` block.** `tests/conftest.py` has a session-autouse fixture that opens a PostgreSQL connection as soon as pytest loads. `make demo` runs with the dev DB up, so the pytest path succeeds during capture — but `uvx showboat verify` (called by `scripts/check-demo.sh` during `make quality`) re-executes the `exec` block on a clean host with no DB, so the fixture fails and the whole demo is rejected. For verify-safe proof of a test assertion, import the test module directly and call its functions:

```bash
uvx showboat exec "$DEMO_FILE" bash \
  'python3 -c "import sys; sys.path.insert(0, \"tests\"); import test_foo as t; t.test_one(); t.test_two(); print(\"2 assertions passed\")"'
```

The session-autouse fixture in `conftest.py` only fires when pytest loads `conftest.py`, which only happens when pytest itself runs. A plain `python3 -c "import …"` imports just the test module and does NOT trigger conftest — so `showboat verify` passes with or without Postgres.

Then run: `make demo`

If `make demo` succeeds, your `demo.md` is ready.

### Frontend / UI demo

Write `docs/demos/<branch>/demo-script.sh`:

```bash
#!/usr/bin/env bash
# Demo: <feature description>
# Called by make demo (server + DB already running).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"  # sets $BACKEND_PORT, $FRONTEND_PORT

# Normalize slashes in branch names — scripts/check-demo.sh maps feat/foo → feat-foo.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

# `uvx showboat init` refuses to overwrite — delete the file so `make demo` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" "<stakeholder sentence here>"

# Start Rodney (headless browser — never open a visible browser)
uvx rodney start

# Show before state
uvx showboat note "$DEMO_FILE" "Before: <describe initial state>"
uvx rodney open "http://localhost:${FRONTEND_PORT}"
uvx rodney waitstable
uvx rodney screenshot "$DEMO_DIR/before.png"
uvx showboat image "$DEMO_FILE" "$DEMO_DIR/before.png" "Before: <caption>"

# Perform the action
# ... rodney click/type commands ...

# Show after state
uvx showboat note "$DEMO_FILE" "After: <describe new state>"
uvx rodney waitstable
uvx rodney screenshot "$DEMO_DIR/after.png"
uvx showboat image "$DEMO_FILE" "$DEMO_DIR/after.png" "After: <caption>"

uvx rodney stop
uvx showboat verify "$DEMO_FILE"
```

Then run: `make demo`

**Rodney rules:**
- Always call `waitstable` before taking a screenshot — it waits for network activity and animations to settle
- Show state transitions: the before screenshot proves the old state existed; the after screenshot proves the new state exists
- All screenshots go into Showboat via `uvx showboat image`
- Never open a visible browser — always use headless Rodney

---

## Step 6 — PR body

Section order is non-negotiable. Demo (or exemption) goes first.

**If you wrote a `demo.md`:**

```markdown
## Demo

<stakeholder sentence>

Demo document: [`docs/demos/<branch>/demo.md`](docs/demos/<branch>/demo.md)
Re-verify: `uvx showboat verify docs/demos/<branch>/demo.md`

<screenshots if frontend>

## Tests

<what tests were added, delta from baseline, strategy reasoning — not just pass counts>

## Changes

<what changed and why — bullet points>
```

**If the classifier returned `no_demo` and you committed `exemption.md`:**

```markdown
## Demo

**No demo — classifier exemption (`docs/demos/<branch>/exemption.md`).**

<one-line paraphrase of the classifier's `reasoning` — not the full JSON>

Verify: `bash scripts/check-demo.sh` (recomputes the diff hash and passes when the exemption is fresh).

## Tests

...

## Changes

...
```

Do not write the PR body until either `make demo` has run successfully (if you have a demo) or `bash scripts/check-demo.sh` prints `Exemption verified` (if you have an exemption).

**If Step 0 auto-exempted and you wrote no file:** paste the one-line summary from Step 0's output into the PR body; `check-demo.sh` will reach the same conclusion on its own.

---

## Verification

Before creating the PR, run:

```bash
make demo-check
```

This calls `scripts/check-demo.sh` which tries three acceptance paths in order:

1. **Static allowlist** — every changed file matches the widened regex. Exit 0.
2. **`demo.md` present** — run `uvx showboat verify`. Pass → exit 0.
3. **`exemption.md` present** — parse frontmatter, recompute `sha256(git diff $MERGE_BASE HEAD)`, compare against stored `diff_hash`. Match → exit 0. Mismatch → exit 1 with "exemption is stale for current diff".

If both `demo.md` and `exemption.md` exist, `demo.md` wins.

`make quality` also calls `demo-check` as its last step — your commit will be blocked if the demo is missing, the demo fails verification, or the exemption's hash is stale.

**Note:** `uvx showboat verify` re-runs all captured commands. It requires the same server state as when you recorded the demo. Run verify as part of `make demo` (already built into the demo-script.sh template above), not as a standalone step after the server is down.

**Determinism — `verify` is byte-exact.** Any `exec` block whose captured output includes timings (`in 50.00s`), token counts, PIDs, memory addresses, ISO timestamps, or other non-reproducible noise will fail re-verification on the next run even though the underlying assertion still holds. Reduce the captured output to a deterministic summary BEFORE the command's output lands in showboat:

- `pytest ... | grep -oE "[0-9]+ passed"` → captures only `558 passed`, not the `in 101.95s` tail.
- `codex exec ... | grep -q "^OK$" && echo OK || echo FAIL` → captures only `OK`/`FAIL`, not the session preamble and token counts.
- Explicit `echo` of the interesting boolean (`echo "fix applied: $(grep -c "\-\-dangerously-bypass" src/gateway/review_engine.py)"`) rather than streaming a whole file.

Rule of thumb: if you couldn't bet that two successive runs produce **identical bytes**, reduce it first. Raw streaming of `pytest`, `codex`, `gh`, `curl -v`, or anything with a progress bar will bite on the next `make demo-check`.
