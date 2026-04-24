# Demo Classifier — Replace Blanket Demo Gate with Diff-Aware Decision

## Problem

`make demo-check` currently forces a `docs/demos/<branch>/demo.md` on every
non-docs-only branch. The only escape is a narrow static allowlist in
`scripts/check-demo.sh` (`docs/`, `CLAUDE.md`, `.claude/`, `scripts/`,
`.github/`, `tests/e2e/`, `package-lock.json`). Anything else — Makefile
edits, internal refactors, test changes, plumbing — trips the gate.

Agents respond to the gate, not to the intent. When a PR has nothing a
stakeholder would watch, the agent synthesises a Showboat document (often
grep/awk over the Makefile or a script) that satisfies `showboat verify`
but carries zero stakeholder value. The demo becomes a tax paid to the
hook, and the hook stops protecting anything it was meant to protect.

Concrete example: `docs/demos/make-invariants-fail-fast-in-quality/demo.md`
uses `awk` against `Makefile` to prove target ordering. That is a test,
not a demo. It shipped because the gate demanded an artifact.

## Goal

Demos should exist for PRs with user-observable behaviour change
(HTTP routes, MCP tools, frontend components on user-visible routes,
CLI output). PRs that don't change user-observable behaviour should
skip the demo without friction — and without the agent having to
negotiate exemption copy to pass the reviewer.

The exemption path must be as easy for the agent as writing a demo.
If exempting is harder or scarier than synthesising, agents synthesise.

## Non-Goals

- Not changing `make demo`, `scripts/run-demo.sh`, the Showboat/Rodney
  wrappers, or the `docs/demos/<branch>/` directory layout for real
  demos.
- Not removing the demo gate. Demos remain required when warranted.
- Not introducing a "demo-lite" or "demo-optional" artifact type. There
  is `demo.md` (real demo) and `exemption.md` (no demo, justified).

## Design

### Flow overview

```
agent finishes code  →  invokes `cloglog:demo` skill
                            │
                            ▼
            ┌──── Static allowlist check ────┐
            │  Every changed file matches    │
            │  docs/, tests/, Makefile,      │
            │  scripts/, .github/, .claude/, │
            │  .cloglog/, plugins/*/hooks/,  │
            │  *.lock, CLAUDE.md,            │
            │  pyproject.toml, ruff.toml ?   │
            └────────────┬───────────────────┘
                         │
                 yes ────┴──── no
                  │             │
                  ▼             ▼
        auto-exempt      spawn `demo-classifier` subagent
        (no file         (reads git diff, emits verdict)
        written)                │
                     needs_demo ┴── no_demo
                        │             │
                        ▼             ▼
                produce demo.md   write exemption.md
                                  (classifier rationale
                                   + diff hash)

        make quality → check-demo.sh accepts any of:
          • static allowlist match
          • demo.md that passes showboat verify
          • exemption.md whose diff_hash matches current diff

        after PR opens → demo-reviewer + codex reviewer audit
          • if demo.md: stakeholder framing + substance + screenshots
          • if exemption.md: is the no_demo call justified by the diff?
          (both post comments; neither blocks the merge)
```

### Key decisions (from brainstorming)

- **Binary verdict.** Classifier outputs `needs_demo` or `no_demo`.
  Unsure collapses to `needs_demo` — err toward demo on doubt.
- **Committed exemption.** `exemption.md` is git-tracked under
  `docs/demos/<branch>/exemption.md` so the local `make quality` can
  verify it without the PR existing yet.
- **Comment-only reviewer pressure.** Post-PR reviewers (demo-reviewer,
  codex) comment on bad exemptions. They do not block merge. The human
  user merges.
- **No malicious-party hardening.** The exemption's `diff_hash` catches
  drift (agent adds code after classifying). It does not defend against
  a human hand-crafting an exemption with a valid hash — that's fine;
  reviewers are the check.

### Component 1 — Widen the static allowlist

**File:** `scripts/check-demo.sh`

Current regex (inverse — what's **excluded** from allowlist):
```
^docs/|^CLAUDE\.md|^\.claude/|^scripts/|^\.github/|^tests/e2e/|package-lock\.json$
```

New regex (same semantics — any changed file *not* matching is a reason
to not auto-exempt):
```
^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|^tests/|^Makefile$|^plugins/[^/]+/hooks/|^pyproject\.toml$|^ruff\.toml$|\.lock$
```

Added paths:
- `tests/` (all tests, not just e2e — unit/integration/property
  tests are equally unobservable to a stakeholder).
- `Makefile` (build orchestration, not user behaviour).
- `plugins/*/hooks/` (plugin infrastructure — not user-observable code).
- `.cloglog/` (project config).
- `pyproject.toml`, `ruff.toml`, `*.lock` (tooling/deps).

If every changed file matches the allowlist → `check-demo.sh` exits 0.
No subagent, no artifact, no demo, no exemption file required.

### Component 2 — `demo-classifier` subagent

**File:** `.claude/agents/demo-classifier.md` *(new)*

**Frontmatter:**
```yaml
---
name: demo-classifier
description: Binary-verdict classifier — decides whether a branch diff has user-observable behaviour change requiring a stakeholder demo, or is internal-only and qualifies for an exemption
tools:
  - Read
  - Bash
  - Glob
  - Grep
---
```

**Prompt body** (rules the classifier applies):

- Read `git diff origin/main...HEAD` and `git diff --name-only origin/main...HEAD`.
- Verdict is `needs_demo` if the diff adds or changes any of:
  - HTTP route decorators (new/changed `@router.{get,post,patch,put,delete}` in `src/gateway/**/routes.py`, new path, changed response shape).
  - React components rendered on a user-visible route, or user-observable UI behaviour (not pure refactors of component internals).
  - MCP tool definitions (new tool file in `mcp-server/src/tools/`, renamed tool, changed input/output schema).
  - CLI output surface (`src/**/cli.py`, user-invoked `scripts/*.sh`, `Makefile` targets whose stdout a user reads).
  - DB migration that changes user-observable data shape (backfill, new enum value a user sees).
- Verdict is `no_demo` if the diff is:
  - Pure internal refactor (moves code, renames private symbols, extracts helpers, no external interface change).
  - Test-only (new/changed tests, no production code).
  - Logging/metric-only (adding observability without changing behaviour).
  - Dependency/lock-file bumps with no call-site change.
  - Internal plumbing (repository/service wiring with no change to external observation).
- Unsure → `needs_demo`.

**Output: strict JSON on stdout, one object, no prose around it:**
```json
{
  "verdict": "needs_demo" | "no_demo",
  "reasoning": "Two parts: (a) what signal/counter-signal you saw in the diff — cite specific files or symbols; (b) counterfactual — what would have pushed the verdict the other way and why it wasn't present",
  "diff_hash": "<sha256 of the unified diff>",
  "suggested_demo_shape": "backend-curl" | "frontend-screenshot" | "mcp-tool-exec" | "cli-exec" | null
}
```

The caller parses this JSON. The classifier does not write any files.

### Component 3 — Updated `cloglog:demo` skill

**File:** `plugins/cloglog/skills/demo/SKILL.md`

Prepend two steps in front of the existing Steps 1–6.

**Step 0 — Static fast-path:**

```bash
BASE=$(git merge-base origin/main HEAD 2>/dev/null || git merge-base main HEAD)
CHANGED=$(git diff --name-only "$BASE"..HEAD)
NONALLOWLIST=$(echo "$CHANGED" | grep -vE '^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|^tests/|^Makefile$|^plugins/[^/]+/hooks/|^pyproject\.toml$|^ruff\.toml$|\.lock$' || true)

if [[ -z "$NONALLOWLIST" ]]; then
  echo "Auto-exempt: all changes are in the static allowlist."
  # Skill exits. No file written. scripts/check-demo.sh will reach the
  # same conclusion with the same regex.
  exit 0
fi
```

**Step 1 — Classifier (only runs if Step 0 did not auto-exempt):**

Agent spawns `demo-classifier` via the `Agent` tool, passing the diff
and changed-file list in the prompt. Parses the JSON verdict.

- `verdict: "no_demo"` → skill writes `docs/demos/<branch>/exemption.md`:

  ```markdown
  ---
  verdict: no_demo
  diff_hash: <sha256>
  classifier: demo-classifier
  generated_at: <iso8601>
  ---

  ## Why no demo

  <classifier reasoning — signal, counter-signal, counterfactual>

  ## Changed files

  <git diff --name-only output, one per line>
  ```

  Agent commits `exemption.md`. Skill exits.

- `verdict: "needs_demo"` → skill proceeds to the existing Steps 2–6
  (stakeholder sentence, decision table, demo script, Showboat/Rodney,
  PR body). `suggested_demo_shape` seeds the decision table's first
  row: "Classifier suggests: `<shape>` — start there."

**Re-running after further code changes:** `diff_hash` in `exemption.md`
becomes stale when the diff changes. `scripts/check-demo.sh` detects
mismatch and fails, forcing re-classification. No silent-trust path.

### Component 4 — Updated `scripts/check-demo.sh`

Three acceptance paths:

1. **Static allowlist** — same widened regex as Step 0 of the skill.
   Match → exit 0.
2. **`docs/demos/<branch>/demo.md` present** — run
   `uvx showboat verify`. Pass → exit 0.
3. **`docs/demos/<branch>/exemption.md` present** — parse frontmatter,
   compute `sha256` of current `git diff origin/main...HEAD`, compare
   against stored `diff_hash`.
   - Match → exit 0.
   - Mismatch → exit 1, message: "exemption is stale for current diff
     — re-run `cloglog:demo` skill to reclassify."

If both `demo.md` and `exemption.md` exist, `demo.md` wins.

### Component 5 — Updated `demo-reviewer` subagent

**File:** `.claude/agents/demo-reviewer.md`

Add two new dimensions to the existing three-dimension rubric.

**Dimension D — Exemption audit** (fires only when `exemption.md`
exists, not `demo.md`):

- Read the exemption's reasoning.
- Read `git diff origin/main...HEAD` independently.
- Test the classifier's `no_demo` verdict against what the reviewer
  sees:
  - Diff touches `frontend/src/**` with new render logic
    → **invalid exemption, demand screenshots.**
  - Diff adds/changes any `@router.*` decorator in `src/gateway/`
    → **invalid exemption, demand curl demo.**
  - Diff adds a new tool file in `mcp-server/src/tools/`
    → **invalid exemption, demand MCP tool-exec demo.**
  - Otherwise, if the reviewer's read of the diff agrees with the
    classifier's reasoning → **valid exemption.**

**Dimension E — Missing-screenshot guard** (fires when `demo.md`
exists):

- Diff touches `frontend/src/**` AND `demo.md` has zero `image`
  blocks → **needs revision, demand Rodney screenshots.**

Both dimensions collapse into the existing single "Overall:
approved / needs revision" verdict. One comment per pass.

### Component 6 — Updated codex-review-prompt

**File:** `plugins/cloglog/templates/codex-review-prompt.md`

Add one section, placed after "What NOT to report" so it cannot be
confused with a surface check:

```markdown
## Demo expectations

Independent of the demo-reviewer, you are also an auditor for demo
coverage.

Read `docs/demos/<branch>/` if it exists.

- If the diff adds user-observable behaviour (HTTP route, MCP tool,
  frontend component on a visible route, CLI output) AND the directory
  contains only `exemption.md` (no `demo.md`), flag it as a finding.
  Cite which file(s) in the diff introduce the user-observable change.
- If the diff adds frontend behaviour AND `demo.md` exists but contains
  no screenshots (no Showboat `image` blocks), flag it. Screenshots
  are the proof a stakeholder cares about for frontend work.
- If the diff is purely internal (refactor, logging, plumbing) and
  there is an `exemption.md`, do not flag — this is the intended path.

This check is orthogonal to the rest of your review: a PR can have a
correct patch AND insufficient demo. Report both.

Comment-only — do not gate or request changes for demo issues.
```

Rationale for splitting demo audit across two reviewers (demo-reviewer
and codex): different models, different viewpoints. If codex thinks a
change deserved screenshots and Claude missed it, we still catch it.
Two independent pressures on the classifier keep it honest.

## Rollout order

Six changes, landed in this order so each step is individually
mergeable without breaking the gate:

1. **Widen `scripts/check-demo.sh` allowlist.** Single small PR.
   Immediately retires the worst false positives today, before any
   other moving part exists.
2. **Add `demo-classifier` subagent.** Standalone file — nothing calls
   it yet. Testable on historical PRs manually.
3. **Add `exemption.md` acceptance path to `scripts/check-demo.sh`.**
   Gate accepts the third artifact. No agents produce it yet, so no
   flow change.
4. **Update `cloglog:demo` skill.** Invokes classifier, produces
   `exemption.md`. This is the switch that turns on the new flow.
5. **Update `demo-reviewer` subagent.** Adds exemption-audit and
   missing-screenshot dimensions.
6. **Update codex prompt.** Adds demo-expectations section.

Each step is revertable; no Big Bang.

## Testing strategy

- **Static allowlist widening** — add a pin test (like existing invariants)
  that runs `check-demo.sh` against a fabricated diff containing only
  allowlisted paths and asserts exit 0, and against a diff containing
  one `src/gateway/routes.py` file and asserts non-zero exit. Pin test
  lives in `tests/` so it runs under `make invariants`.
- **`exemption.md` diff-hash verification** — pin test that writes an
  exemption with a known hash, synthesises a diff with a different
  hash, runs `check-demo.sh`, asserts non-zero exit with the stale
  message.
- **Classifier prompt** — no automated test; verify on ~5 historical
  PRs manually by running the subagent against their diffs and
  checking verdicts match human intuition. Record the verdicts in the
  implementation plan's test report.
- **Skill flow** — an integration demo: synthesise two test branches
  (one needs_demo, one no_demo), run the skill end-to-end, assert the
  right artifact lands in each.
- **demo-reviewer and codex updates** — test by posting against a
  real PR where the agent claims exemption on a frontend change;
  assert the reviewers' comments contain "invalid exemption" /
  "demand screenshots."

## Files touched

- `scripts/check-demo.sh` — widened allowlist + new exemption path (Components 1 + 4).
- `.claude/agents/demo-classifier.md` — new file (Component 2).
- `plugins/cloglog/skills/demo/SKILL.md` — new Steps 0 and 1 (Component 3).
- `.claude/agents/demo-reviewer.md` — two new dimensions (Component 5).
- `plugins/cloglog/templates/codex-review-prompt.md` — new section (Component 6).
- `tests/test_check_demo_allowlist.py` — new pin test.
- `tests/test_check_demo_exemption_hash.py` — new pin test.

## Out of scope

- Restructuring the `docs/demos/<branch>/` layout.
- Changing `make demo`, `run-demo.sh`, or Showboat/Rodney wrapping.
- Adding blocking behaviour to any reviewer.
- Replacing the user as the final merge gate.
