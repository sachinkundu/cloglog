# F-51 Demo Classifier — Implementation Plan

**Design spec:** `docs/superpowers/specs/2026-04-24-demo-classifier-design.md` (authoritative).
**Feature:** F-51 — Demo Classifier — Diff-Aware Demo Gate.
**Task:** T-289 — Implement diff-aware demo classifier end-to-end.
**Branch:** `wt-f51-demo-classifier` (sequential PRs off `origin/main`).

This plan turns the six components in the spec's Section 7 into concrete
file-level steps with acceptance criteria, one PR per step. Each PR must
keep `make quality` green.

## Rollout order (one branch, sequential PRs)

Per the task prompt, sequential PRs on one branch — the review/merge
latency is tolerable and six in-flight branches would be operational
complexity without payoff. After each merge, rebase `wt-f51-demo-classifier`
on `origin/main` before starting the next step.

---

## PR 1 — Widen `scripts/check-demo.sh` allowlist (Component 1)

**Also contains the first commit:** the design spec and this plan.

### Files touched
- `scripts/check-demo.sh` — widen the `grep -vE '...'` regex on line 31.
- `docs/superpowers/specs/2026-04-24-demo-classifier-design.md` — `git add` (already written).
- `docs/superpowers/plans/2026-04-24-demo-classifier-impl-plan.md` — this file.
- `tests/test_check_demo_allowlist.py` — new pin test.
- `docs/invariants.md` — add an entry pointing at the new pin test.

### Regex change
Replace
```
^docs/|^CLAUDE\.md|^\.claude/|^scripts/|^\.github/|^tests/e2e/|package-lock\.json$
```
with
```
^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|^tests/|^Makefile$|^plugins/[^/]+/hooks/|^pyproject\.toml$|^ruff\.toml$|\.lock$
```
Both in the `CODE_CHANGES` line (line 31) and embedded again as a
constant the classifier skill will reuse (PR 4 adds the skill copy — PR 1
only updates the script).

### Pin test (`tests/test_check_demo_allowlist.py`)
- Spawn a temporary git repo (or use a fixture base), stage files that
  match the allowlist only, run `scripts/check-demo.sh` with
  `DEMO_FEATURE=`, assert exit 0.
- Stage a file that does NOT match (e.g., `src/gateway/routes.py`),
  assert exit 1.
- The test must not require PostgreSQL or any service.

### Acceptance
- `make invariants` passes (new pin test included).
- `make demo-check` skips on a fabricated docs-only-with-Makefile branch.
- `make quality` still green on this PR (auto-exempts under widened
  allowlist: only `scripts/`, `docs/`, `tests/`).

### Demo artifact
Auto-exempt (changes only under `scripts/`, `docs/`, `tests/`,
`plugins/cloglog/...` if needed). No `demo.md` or `exemption.md` yet —
the exemption path does not exist until PR 3.

---

## PR 2 — Add `demo-classifier` subagent (Component 2)

### Files touched
- `.claude/agents/demo-classifier.md` — new.

### Frontmatter and prompt body
Per spec Section "Component 2". Verbatim rules:
- Verdict is `needs_demo` for HTTP route changes, React components on
  user-visible routes, MCP tool definitions, CLI output surface, DB
  migrations with user-observable data shape change.
- Verdict is `no_demo` for pure internal refactor, test-only, logging/
  metric-only, dep/lock bumps, internal plumbing.
- Unsure → `needs_demo`.
- Output strict JSON on stdout: `{verdict, reasoning, diff_hash,
  suggested_demo_shape}`. No prose around it.
- Classifier does not write files.

### Acceptance
- File exists and parses as valid markdown with YAML frontmatter.
- Nothing references it yet (standalone), so no behavior change.

### Demo artifact
Auto-exempt (`.claude/` allowlisted).

---

## PR 3 — `exemption.md` acceptance path in `scripts/check-demo.sh` (Component 4)

### Files touched
- `scripts/check-demo.sh` — add exemption-path branch after the
  existing `demo.md` check.
- `tests/test_check_demo_exemption_hash.py` — new pin test.
- `docs/invariants.md` — add entry for the diff-hash invariant.

### Script change
After locating `DEMO_DIR`, check for `exemption.md`:
- If `demo.md` exists, keep current showboat verify path (demo.md wins).
- Else if `exemption.md` exists, parse frontmatter for `diff_hash`,
  compute `sha256` of `git diff origin/main...HEAD` (same merge-base
  logic as `CODE_CHANGES`), compare.
  - Match → exit 0.
  - Mismatch → exit 1 with message "exemption is stale for current diff
    — re-run `cloglog:demo` skill to reclassify."
- Else → existing missing-demo error.

### Frontmatter parsing
Bash-only: `awk '/^diff_hash:/ {print $2; exit}' exemption.md` to read
the hash. No YAML parser needed (matches the hook-script rule in
`docs/invariants.md` about avoiding `python3 -c 'import yaml'`).

### Pin test (`tests/test_check_demo_exemption_hash.py`)
- Fabricate a repo with an `exemption.md` whose `diff_hash` matches the
  current diff → assert exit 0.
- Fabricate a repo where hash mismatches → assert non-zero exit and
  message contains "exemption is stale".

### Acceptance
- `make invariants` passes (both new pin tests).
- `make demo-check` on this PR: allowlisted (no `src/`).
- Script's three-path logic (allowlist, demo.md, exemption.md) is
  exhaustive.

### Demo artifact
Auto-exempt (`scripts/`, `tests/`, `docs/`).

---

## PR 4 — Update `cloglog:demo` skill (Component 3)

### Files touched
- `plugins/cloglog/skills/demo/SKILL.md` — prepend Step 0 and Step 1
  in front of current Steps 1–6. Renumber existing steps to 2–7.
- `plugins/cloglog/skills/demo/SKILL.md` — remove the old "Step 5 —
  Exemption declaration" block (it is replaced by the new Step 1's
  `exemption.md` path).

### Step 0 — Static fast-path
Bash block from spec. Exit 0 when all changed files are allowlisted.
Regex must be identical to the one in `scripts/check-demo.sh` (PR 1).

### Step 1 — Classifier invocation
- Spawn `demo-classifier` via the `Agent` tool.
- Parse JSON verdict.
- If `no_demo`: write `docs/demos/<branch>/exemption.md` with frontmatter
  (`verdict`, `diff_hash`, `classifier`, `generated_at`), `Why no demo`
  section, and `Changed files` list. Commit.
- If `needs_demo`: proceed to renumbered Steps 2–7. Seed the decision
  table with `suggested_demo_shape`.

### Acceptance
- Manual dry-run of the skill against a fabricated no-demo diff writes
  a valid `exemption.md`.
- Manual dry-run against a fabricated needs-demo diff advances to the
  existing demo steps.
- Old exemption-declaration block is gone (one exemption mechanism,
  committed `exemption.md`, not inline PR-body text).

### Demo artifact
Auto-exempt (`plugins/cloglog/skills/`).

---

## PR 5 — Update `demo-reviewer` subagent (Component 5)

### Files touched
- `.claude/agents/demo-reviewer.md` — add Dimension D (exemption audit)
  and Dimension E (missing-screenshot guard). Update comment template
  table to list five dimensions. Keep single collapsed verdict.

### Dimension D (exemption audit, fires when only `exemption.md` exists)
- Read exemption's reasoning + independently read diff.
- Flag as **invalid exemption** if diff touches `frontend/src/**`,
  `@router.*` decorator in `src/gateway/`, or new tool in
  `mcp-server/src/tools/`.
- Otherwise, if reasoning agrees with diff → **valid exemption**.

### Dimension E (missing-screenshot guard, fires when `demo.md` exists)
- Diff touches `frontend/src/**` AND `demo.md` has zero `image` blocks
  → **needs revision, demand Rodney screenshots.**

### Acceptance
- File parses as markdown.
- Comment template includes both new dimensions.
- Existing three-dimension rubric still fires on `demo.md` paths.

### Demo artifact
Auto-exempt (`.claude/`).

---

## PR 6 — Update codex-review-prompt (Component 6)

### Files touched
- `plugins/cloglog/templates/codex-review-prompt.md` — append the
  "## Demo expectations" section after the existing "What NOT to
  report" section.

### Section content
Verbatim from spec Component 6. Key points:
- Flag PRs with user-observable change + only `exemption.md`.
- Flag frontend diffs with `demo.md` but zero screenshots.
- Do not flag purely internal diffs with `exemption.md`.
- Comment-only — do not gate or request changes.

### Acceptance
- File contains the new section.
- Section lives after "What NOT to report" (spec-specified placement
  so codex treats it as substantive audit, not a surface check).

### Demo artifact
Auto-exempt (`plugins/cloglog/templates/`).

---

## Testing strategy (cumulative, per PR)

- **PR 1, 3:** new pin tests added to `make invariants` — they run on
  every `make quality` via the invariants-fail-fast target.
- **PR 2, 4, 5, 6:** no automated tests (prompt/skill/agent docs).
  Manual verification on a fabricated diff during implementation.
- **End-to-end:** during PR 3 or PR 4 merge wave, the branch itself is
  all-allowlisted so we won't see the exemption path fire on the
  feature's own PRs. To prove the end-to-end exit condition, produce a
  seventh "proof" PR before unregistering: a trivial internal refactor
  under `src/` that should classify `no_demo` and land via
  `exemption.md`. This is the proof-of-work artifact for the exit
  condition (see Workflow step 10 of `AGENT_PROMPT.md`).

## Proof-PR for exit condition

After PR 6 merges, open a small no-demo PR (e.g., extract a helper in
`src/gateway/` with no behavior change). Run the updated skill — it
should write `exemption.md`. Merge that PR. That flight exercises:
- the new classifier,
- the committed `exemption.md`,
- `check-demo.sh` exemption path,
- demo-reviewer Dimension D comment on the exemption,
- codex "Demo expectations" section firing.

Only after observing those comments do we unregister.

## Out of scope (explicit, per spec)

- No change to `make demo`, `run-demo.sh`, Showboat/Rodney wrappers.
- No restructuring of `docs/demos/<branch>/`.
- No blocking behavior on any reviewer.
- No replacement of the user as final merge gate.
