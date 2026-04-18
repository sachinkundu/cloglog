# F-45 Implementation Plan: Agent Demo Skill

**Spec:** `docs/superpowers/specs/2026-04-18-f45-agent-demo-skill-design.md`
**Feature:** F-45 — Agent Demo Skill (Proof-of-Work with Showboat & Rodney)

---

## Overview

F-45 adds a `demo` skill that enforces proof-of-work demos in every agent PR. It has two enforcement layers:

- **Behavioral (soft):** `plugins/cloglog/agents/worktree-agent.md` gains an explicit checkpoint — agents invoke the demo skill before creating a PR
- **Technical (hard):** `make quality` gains a `demo-check` step — a broken or missing demo blocks the commit via the pre-commit hook

Supporting pieces: the skill itself, a demo reviewer agent, and a worktree-agent launch template update.

### Current State

The following already exist:
- `scripts/check-demo.sh` — full demo-check logic (branch detection, docs-only bypass, showboat verify). No changes needed.
- `scripts/run-demo.sh` — demo orchestration (infra, server start, demo-script.sh runner). **Needs one fix** (see Task 0).
- `make demo` and `make demo-check` targets
- Extensive `docs/demos/` examples covering backend, frontend, and MCP demo patterns

What does NOT exist yet (the gap):
- `plugins/cloglog/skills/demo/SKILL.md` — the skill itself
- `demo-check` is not called by `make quality`
- `worktree-agent.md` has no demo skill invocation step
- `launch/SKILL.md` AGENT_PROMPT template has no demo skill step
- `github-bot/SKILL.md` PR template has no `## Demo` section
- No demo reviewer agent definition

---

## Implementation Tasks

### Task 0 — Fix `run-demo.sh` branch detection

**File:** `scripts/run-demo.sh` *(modify)*

**What to change:**

`run-demo.sh` currently detects the demo feature only from `f[0-9]*-*` branch names. On any other branch (e.g., `wt-f45-agent-demo-impl`), it exits with `Cannot detect feature` — even if `docs/demos/wt-f45-agent-demo-impl/demo.md` exists. This makes `make demo` unusable from worktree branches, which are the standard agent branch naming pattern.

Fix: after the `f[0-9]*-*` case fails to match, fall back to the full branch name:

```bash
if [[ -z "$FEATURE" ]]; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  case "$BRANCH" in
    f[0-9]*-*)
      FEATURE=$(echo "$BRANCH" | grep -oP '^f\d+' || echo "")
      ;;
    *)
      # Fall back to the full branch name — check-demo.sh already uses this convention
      FEATURE="$BRANCH"
      ;;
  esac
fi
```

This makes the feature detection consistent with `check-demo.sh`, which already uses the full branch name (normalized) as the lookup key.

**Acceptance criteria:**
- `make demo` succeeds on a branch named `wt-f45-agent-demo-impl` when `docs/demos/wt-f45-agent-demo-impl/demo.md` exists
- `make demo` still works on `f[0-9]*-*` branches (existing behavior preserved)
- `DEMO_FEATURE` env var override still takes precedence (existing behavior preserved)

**Scope:** Small (~5 lines changed)

**Dependency:** None (fix this before Task 1 documents the demo directory convention, so the convention actually works end-to-end)

---

### Task 1 — Create the demo skill

**File:** `plugins/cloglog/skills/demo/SKILL.md` *(create)*

**What to create:**

A skill that guides agents through the proof-of-work demo decision tree. The skill is invoked once, before creating a PR. It must be actionable — every section maps to commands the agent runs.

Structure:
1. **Preamble** — "Stop and ask: what would I show on demo day?" One sentence. Sets the mindset.
2. **Step 1 — State the feature** — Write one sentence from the stakeholder's view. Examples of good vs. bad.
3. **Step 2 — Demo decision table** — Same table as the spec (backend/frontend/MCP/combo/docs). Each row: what changed → what to show → capture method.
4. **Step 3 — Show the journey** — Before, action, after. Not just happy path.
5. **Step 4 — Produce the demo** — Two subsections with copy-paste shell commands:
   - **Backend/API/CLI:** `uvx showboat init/note/exec/verify` sequence
   - **Frontend/UI:** `uvx rodney start` → `uvx showboat init` → `uvx rodney open/waitstable/screenshot` → `uvx showboat image/note` → `uvx rodney stop` → `uvx showboat verify`
6. **Step 5 — Exemption declaration** — When to declare no demo. Valid reasons vs. invalid reasons. Exact text template to paste into PR.
7. **Step 6 — PR body** — PR section ordering with template (Demo first, then Tests, then Changes).
8. **Rodney rules sidebar** — Always `waitstable`, show state transitions, screenshots go into Showboat.

**Demo directory convention:** `docs/demos/<branch-name>/demo.md`. Branch name is the demo dir identifier (matches `check-demo.sh` lookup logic).

**Acceptance criteria:**
- Skill exists at `plugins/cloglog/skills/demo/SKILL.md`
- Frontmatter: `name: demo`, `description: Proof-of-work demo with Showboat and Rodney — invoked before every PR`, `user-invocable: false`
- Every command in the skill is copy-paste runnable (no pseudocode)
- Exemption template is word-for-word pasteable into a PR body
- PR body section ordering matches spec exactly

**Scope:** Medium (primary deliverable — ~100-150 lines)

---

### Task 2 — Add `demo-check` to `make quality`

**File:** `Makefile` *(modify)*

**What to change:**

The `quality` target currently runs: lint → typecheck → tests+coverage → contract-check.

Add `demo-check` as the **last step before the final "PASSED" line**:

```makefile
quality: ## Run full quality gate (lint + typecheck + test + coverage)
    @echo "── Backend ─────────────────────────────"
    # ... existing steps unchanged ...
    @echo ""
    @echo "  Contract:"
    @$(MAKE) --no-print-directory contract-check && echo "    compliant          ✓" || (echo "    FAILED ✗" && exit 1)
    @echo ""
    @echo "  Demo:"
    @$(MAKE) --no-print-directory demo-check && echo "    verified           ✓" || (echo "    FAILED ✗" && exit 1)
    @echo ""
    @echo "── Quality gate: PASSED ────────────────"
```

The `demo-check` target and `scripts/check-demo.sh` already handle all the logic:
- Skips on main branch
- Skips docs-only branches
- Errors if demo missing
- Runs `uvx showboat verify` if showboat available

**No changes needed to `scripts/check-demo.sh` or `scripts/run-demo.sh`.**

**Acceptance criteria:**
- `make quality` calls `make demo-check` as the last substantive step
- `make quality` fails with a clear message if demo is missing (on a code-change branch)
- `make quality` still passes on main branch (check-demo.sh handles this)
- The existing quality output format is preserved; only the demo step is added

**Scope:** Small (~5 lines)

**Dependency:** Task 1 must exist first (the step references the skill conceptually, though not technically)

---

### Task 3 — Update `worktree-agent.md` — add demo checkpoint

**File:** `plugins/cloglog/agents/worktree-agent.md` *(modify)*

**What to change:**

In the **Impl Task** section, currently step 4 is:
> Create a PR with: Summary, Demo, Test Report

Replace this with a two-step sequence:

```
3. Before creating a PR — invoke the demo skill
   Invoke Skill({skill: "cloglog:demo"}) to produce the proof-of-work demo.
   This is a named checkpoint, not optional. The skill walks you through the
   decision tree: what to demo, how to capture it, and the PR body format.
   Do not skip this step even if you believe the change is minor.

4. Create a PR using the github-bot skill with sections in this order:
   - **## Demo** — stakeholder sentence + link to demo.md + re-verify command + screenshots
   - **## Tests** — what tests were added, delta from baseline, strategy reasoning
   - **## Changes** — what changed and why
```

Also update the **PR Workflow** section at the bottom:

Current:
> Every PR must include: Summary, Demo, Test Report

Change to:
> Every impl PR must use this section order: `## Demo`, `## Tests`, `## Changes`
>
> The demo is produced by invoking the demo skill before creating the PR.
> Do not write the PR body until the demo is produced and verified.

**Acceptance criteria:**
- `worktree-agent.md` has an explicit "invoke the demo skill" step in the Impl Task section
- The step comes before "Create a PR" — it is a gate, not an afterthought
- The PR body ordering in the template puts Demo first
- The language makes clear this is non-optional (same framing as the test-writer and code-reviewer subagent steps)

**Scope:** Small (~20 lines changed)

**Dependency:** None (but logically follows Task 1)

---

### Task 4 — Update `launch/SKILL.md` AGENT_PROMPT template

**File:** `plugins/cloglog/skills/launch/SKILL.md` *(modify)*

**What to change:**

The AGENT_PROMPT template in the launch skill (the "Prompt Template" section) has a generic workflow list. The impl step currently says:
> 8. Run the project quality gate
> 9. Create PR using the github-bot skill

Add a demo step between quality gate and PR creation:

```
8. Run the project quality gate
9. Produce proof-of-work demo — invoke the demo skill (cloglog:demo) to
   capture the feature working and generate docs/demos/<branch>/demo.md
10. Create PR using the github-bot skill with the demo document at the top
```

**Acceptance criteria:**
- The AGENT_PROMPT template includes an explicit demo skill step
- The step is numbered between quality gate and PR creation
- Demo document goes at top of PR body

**Scope:** Small (~5 lines)

**Dependency:** Task 1

---

### Task 5 — Create demo reviewer agent definition

**File:** `plugins/cloglog/agents/demo-reviewer.md` *(create)*

**What to create:**

A subagent definition for the demo reviewer. It is invoked by the main agent (or a CI hook) on any PR that has a demo document.

Behavior:
1. Runs `uvx showboat verify docs/demos/<branch>/demo.md`
2. Reads the demo document and checks:
   - Does the opening sentence describe the feature from the stakeholder's view (not "I added X" but "users can now Y")?
   - Does the demo show a user action and outcome (not just test output or log lines)?
   - If an exemption was declared, is the reason in the valid-reasons list?
3. Posts a structured comment to the PR with:
   - `verify` result (pass/fail with output)
   - Stakeholder framing: acceptable / needs revision
   - Exemption: valid / invalid / N/A
   - Overall: approved / needs revision

Format the agent as a `.md` file following the same frontmatter pattern as `test-writer.md` and `migration-validator.md`.

Frontmatter:
```yaml
---
name: demo-reviewer
description: Reviews proof-of-work demo documents — runs showboat verify, checks stakeholder framing, validates exemption declarations
---
```

The agent does NOT have merge authority — it comments, the human decides.

**Note:** The spec calls this a "concept" and says human has final say. The agent definition codifies the evaluation criteria so agents can self-review before submitting.

**Acceptance criteria:**
- `plugins/cloglog/agents/demo-reviewer.md` exists
- Frontmatter has correct name and description
- Agent instructions cover: showboat verify, stakeholder framing check, exemption validation, PR comment format
- Agent correctly identifies the three evaluation dimensions from the spec

**Scope:** Medium (~60-80 lines)

**Dependency:** None (independent of other tasks)

### Task 6 — Update `github-bot/SKILL.md` PR template

**File:** `plugins/cloglog/skills/github-bot/SKILL.md` *(modify)*

**What to change:**

The canonical `gh pr create` example in the `github-bot` skill currently shows:

```bash
GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "$(cat <<'EOF'
## Summary
...

## Test plan
...
EOF
)"
```

This template is what agents copy-paste when creating PRs. It must be updated to reflect the F-45 PR body format (`## Demo` first, then `## Tests`, then `## Changes`):

```bash
GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "$(cat <<'EOF'
## Demo

<One-sentence feature description from the stakeholder's view>

Demo document: [`docs/demos/<branch>/demo.md`](docs/demos/<branch>/demo.md)
Re-verify: `uvx showboat verify docs/demos/<branch>/demo.md`

## Tests

...

## Changes

...
EOF
)"
```

**Acceptance criteria:**
- The `gh pr create` example in `github-bot/SKILL.md` shows `## Demo` as the first section
- The template includes the stakeholder-sentence placeholder and the re-verify command
- The old `## Summary` / `## Test plan` sections are replaced by `## Demo` / `## Tests` / `## Changes`

**Scope:** Small (~15 lines changed)

**Dependency:** Task 1 (the demo skill defines the PR body format; this propagates it to the tool agents actually use)

---

## Task Execution Order

```
Task 0 (run-demo.sh fix)     — first, unblocks end-to-end demo workflow
Task 5 (demo-reviewer agent) — independent, can run in parallel with Task 0
Task 1 (demo skill)          — primary deliverable, after Task 0
Task 2 (quality gate)        — after Task 1
Task 3 (worktree-agent.md)   — after Task 1
Task 4 (launch/SKILL.md)     — after Task 1
Task 6 (github-bot template) — after Task 1 (propagates the canonical format)
```

Since all tasks are in `plugins/cloglog/`, `scripts/`, and `Makefile`, they are in the same worktree scope. No cross-context coordination needed.

**Recommended order for a single-agent implementation:**
1. Task 0 (run-demo.sh fix) — fix the broken demo workflow first
2. Task 1 (demo skill) — establishes the canonical reference for all other tasks
3. Task 2 (Makefile) — immediate technical enforcement
4. Task 3 (worktree-agent.md) — behavioral enforcement
5. Task 4 (launch/SKILL.md) — template propagation
6. Task 6 (github-bot template) — propagate canonical PR format to the tool agents actually use
7. Task 5 (demo-reviewer agent) — independent, do last

---

## Cross-Cutting Concerns

### What NOT to rewrite

`scripts/check-demo.sh` is already production-quality — do not touch it. `scripts/run-demo.sh` needs the single branch-detection fix in Task 0, but nothing else. The demo skill commands should match what these scripts expect (same directory conventions, same `uvx showboat` invocations).

### Demo directory naming convention

`scripts/check-demo.sh` normalizes slashes to hyphens and does a `grep -qi "$FEATURE_NORM"` against `docs/demos/*/`. The demo skill must document the naming convention that produces a match:
- Branch `wt-f45-agent-demo-impl` → demo dir `docs/demos/wt-f45-agent-demo-impl/`
- The skill should tell agents to use their branch name as the demo dir name

### Quality gate integration

The pre-commit hook (`plugins/cloglog/hooks/quality-gate.sh`) runs `make quality`. Adding `demo-check` to `make quality` automatically makes it a commit gate — no hook changes needed.

Verify `quality-gate.sh` calls `make quality` (not a subset):

```bash
grep -n "make quality\|demo-check" plugins/cloglog/hooks/quality-gate.sh
```

If it calls a subset, that subset must also include demo-check.

### Skill registration

The plugin uses filesystem discovery — no manifest registration needed. Skills at `plugins/cloglog/skills/demo/SKILL.md` are automatically discovered. No `package.json` or settings changes needed.

### Worktree scope

All changed files are in the worktree-agent's allowed scope:
- `plugins/cloglog/skills/` ✓
- `plugins/cloglog/agents/` ✓
- `Makefile` — verify this is in scope for the impl worktree before touching it

---

## Risks and Open Questions

### Risk 1: `showboat verify` flakiness in quality gate

`uvx showboat verify` re-runs every captured command. If a command depends on server state (e.g., `curl localhost:8001`), verify fails unless the server is running. `check-demo.sh` already handles this gracefully (skips verify if showboat is unavailable), but agents may hit this during quality gate runs.

**Mitigation:** The demo skill should note that `uvx showboat verify` requires the same server state as when the demo was recorded. Agents should run it as part of `make demo`, not as a standalone step.

### Risk 2: Docs-only branches and the quality gate

The `check-demo.sh` correctly bypasses the demo check for docs-only branches. But the bypass logic uses `git diff $MERGE_BASE --name-only` to detect code changes. If an agent's branch has both code changes and docs, it correctly requires a demo. This is the right behavior — no action needed.

### Risk 3: Demo reviewer agent scope

The spec says the demo reviewer agent "can run `uvx showboat verify` on every PR". This implies it needs to checkout the PR branch, which is a read-only operation. The agent definition should clarify it is read-only (no push permissions) and uses `gh pr checkout` to get the branch.

### Open Question: CI integration

The spec mentions the demo reviewer agent as a "concept" that can be re-run at any point. Should it be wired into CI (GitHub Actions) or remain a manually-invoked agent? F-45 scope: implement the agent definition and document how to invoke it. CI wiring is out of scope for F-45.

---

## Acceptance Criteria for F-45

All from the spec's Success Criteria section:

1. Every impl PR has either a Showboat demo document or a specific written exemption declaration
2. `uvx showboat verify` passes on every demo document before PR is created
3. No demo consists solely of test output, log lines, or migration output
4. The demo describes the feature from the stakeholder's perspective in its opening sentence
5. Frontend PRs include Rodney screenshots embedded in the Showboat document
6. Demo appears at the top of the PR body, before Tests and Changes
7. A demo reviewer agent can re-run `uvx showboat verify` on any merged PR

Testable gate: `make quality` fails on a code-change branch with no `docs/demos/<branch>/demo.md`.
