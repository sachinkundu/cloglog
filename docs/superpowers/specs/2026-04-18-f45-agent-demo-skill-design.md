# F-45: Agent Demo Skill — Proof-of-Work with Showboat & Rodney

## Problem

Agents produce PRs with test reports and implementation summaries, but these prove the pipeline ran — not that the feature works. "Tests passed" is evidence of process. A demo is evidence of outcome. Without a demo, the reviewer must run the app themselves to verify the feature — or trust the agent's description, which defeats the purpose of review.

The secondary problem: when demos are attempted, agents often produce a Showboat document that wraps test output or migration logs and calls it a demo. That's not a demo. A demo shows the feature working from the stakeholder's perspective.

## Core Principle

**The demo is the deliverable. The code is how you get there.**

When an agent finishes implementation, the primary question is not "did the tests pass?" It is "what would I show a stakeholder on demo day?" Tests prove the pipeline. The demo proves the feature. The PR exists to deliver the demo — the demo goes at the top of the PR, not as a footnote.

Tests are essential. They are not the demo.

## Tools

**Showboat** (`uvx showboat`) — executable markdown builder. Agents use it to capture live command output into a reproducible document. Key property: `showboat verify` re-runs every captured command and diffs the output against what was recorded. This makes the demo a machine-checkable contract — a demo reviewer agent can run verify on every PR and flag regressions or drift.

**Rodney** (`uvx rodney`) — headless Chrome CLI. Agents use it to drive a browser, capture screenshots of key UI states, and embed them into the Showboat document. Showboat is the container; Rodney populates it for UI changes.

Both tools are installed on-demand via `uvx` — no permanent dependency required.

## When the Skill Is Invoked

Once, before creating a PR. Not as a checklist item — as a thinking prompt. The agent stops and asks: what would I show on demo day?

## Demo Decision Tree

### Step 1 — State the feature in one sentence from the stakeholder's view

Not: "I added a `pr_merged` field to the task model."
Instead: "Tasks with merged PRs no longer block agents from starting new work."

Write this sentence first. If it's hard to write, the demo scope isn't clear yet.

### Step 2 — Determine demo type based on what changed

| What changed | What to show | Capture method |
|---|---|---|
| Backend API / CLI | Live endpoint or command output | Showboat `exec` with curl or CLI calls |
| Frontend UI | Rendered feature in browser | Showboat `note` + Rodney screenshots via `showboat image` |
| MCP tool | Tool invoked, correct output returned | Showboat `exec` with the MCP call |
| Backend + frontend | Both | Combined Showboat doc with Rodney screenshots |
| Docs / spec / research | The document itself | No Showboat — doc IS the demo |

### Step 3 — Show the journey, not just the happy path

What does it look like before the feature? What does the user do? What is the result? Include relevant error states if the feature handles them.

### Step 4 — Verify before committing

Run `uvx showboat verify docs/demos/<task>/demo.md`. If it fails, the demo is broken — fix the code or the demo before proceeding.

## Producing the Demo

### Backend / API / CLI changes

```bash
uvx showboat init docs/demos/<task>/demo.md "<Feature title>"
uvx showboat note demo.md "What this feature does and why it matters"

# For each key behavior:
uvx showboat exec demo.md "curl -s http://localhost:$BACKEND_PORT/api/v1/..."
uvx showboat note demo.md "What that output proves"

# Verify before committing
uvx showboat verify docs/demos/<task>/demo.md
```

### Frontend / UI changes (Showboat + Rodney)

```bash
uvx rodney start  # headless Chrome

uvx showboat init docs/demos/<task>/demo.md "<Feature title>"
uvx showboat note demo.md "What the user sees and why it matters"

# For each key UI state:
uvx rodney open http://localhost:$FRONTEND_PORT/...
uvx rodney waitstable  # always wait before screenshotting
uvx rodney screenshot docs/demos/<task>/001-initial-state.png
uvx showboat image demo.md "![Initial state](001-initial-state.png)"
uvx showboat note demo.md "What this screenshot proves"

# Show state transitions — before → action → after
uvx rodney click "button#submit"
uvx rodney waitstable
uvx rodney screenshot docs/demos/<task>/002-after-action.png
uvx showboat image demo.md "![After action](002-after-action.png)"
uvx showboat note demo.md "What changed and why it is correct"

uvx rodney stop
uvx showboat verify docs/demos/<task>/demo.md
```

**Rodney rules:**
- Always `waitstable` before screenshotting — captures settled state, not mid-render
- Show state transitions: before → action → after, not just the end state
- Screenshots go into Showboat so `showboat verify` has the full picture and the reviewer agent can process it

## Demo Exemptions

### No demo required — document IS the demo

- Design specs, implementation plans, research documents
- Documentation-only changes (CLAUDE.md, README, API docs, comments)

The PR description links to the document and summarizes what changed. That is sufficient.

### Demo impossible — must declare

Some changes genuinely have nothing to show: a pure internal refactor where external behavior is unchanged, an infrastructure-only change with no user-facing effect.

In these cases the agent must write a specific declaration in the PR:

> "Demo not produced because: [specific reason]. External behavior is unchanged — the proof is that existing tests still pass with no modifications."

Valid reasons: pure refactor (no observable behavior change), infrastructure-only (no user-facing effect).

Invalid reasons: "it was too complex to demo", "tests cover it", "it's internal".

The demo reviewer agent evaluates the declared reason. If it disagrees, it flags the PR. The human makes the final call.

**Never acceptable:** A Showboat document that wraps test output, log lines, or migration output and presents it as a demo.

## PR Body Structure

The demo is the first thing the reviewer sees:

```markdown
## Demo

<One-sentence feature description from the stakeholder's view>

Demo document: [`docs/demos/<task>/demo.md`](link)
Re-verify: `uvx showboat verify docs/demos/<task>/demo.md`

[Screenshots here if frontend changes]

## Tests
...

## Changes
...
```

## Demo Reviewer Agent

The Showboat document is designed to be machine-verifiable. A demo reviewer agent can run `uvx showboat verify` on every PR and comment if outputs have drifted from what was recorded. This turns the demo into an ongoing contract — not just proof-of-work at PR time, but a regression check that can be re-run at any point.

The demo reviewer agent evaluates:
- Does `showboat verify` pass?
- Does the demo show the feature from the stakeholder's view, or just infrastructure/tests?
- If a demo exemption was declared, is the reason valid?

Human has final say on all reviewer agent decisions.

## Enforcement — How the Skill Gets Run

Two layers ensure agents actually invoke the demo skill before creating a PR:

**1. Agent prompt (behavioral):** The launch skill template includes an explicit step in every agent's workflow: "Before creating a PR, invoke the demo skill." Same pattern as how agents are told to invoke github-bot before pushing. This makes it a named checkpoint in the agent's mental model, not an afterthought.

**2. Quality gate (technical):** `make quality` includes a `demo-check` step that verifies `docs/demos/<task>/demo.md` exists and `showboat verify` passes. The pre-commit hook already runs `make quality`, so a missing or broken demo blocks the commit. Agents cannot create a PR without passing this gate.

The behavioral layer (prompt) ensures agents *think* demo-first. The technical layer (quality gate) ensures they cannot skip it even if they try.

## What This Skill Does NOT Cover

- Automated visual regression (screenshot diffing across PRs)
- Playwright E2E regression suite
- Accessibility auditing
- Project-specific demo requirements (those live in CLAUDE.md)

## Success Criteria

1. Every PR has either a Showboat demo document or a specific written declaration of why a demo is not possible
2. `showboat verify` passes on every demo document before the PR is created
3. No demo consists solely of test output, log lines, or migration output
4. The demo describes the feature from the stakeholder's perspective in its opening sentence
5. Frontend PRs include Rodney screenshots of actual running UI embedded in the Showboat document
6. The demo appears at the top of the PR body, before tests and implementation notes
7. A demo reviewer agent can re-run `showboat verify` on any merged PR and confirm outputs still match
