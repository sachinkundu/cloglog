# Skill Hygiene Lessons

Distilled from *The Complete Guide to Building Skills for Claude* (Anthropic, 2025).
Source PDF: `https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf`

These lessons drive the audit and refactor work in the parent feature. Every task
under this feature should treat them as the rubric — both for "is this skill broken?"
and "what does fixed look like?"

---

## 1. A skill is a recipe, not a research document

> "Skills provide the recipes: step-by-step instructions on how to create something
> valuable."

`SKILL.md` should encode the **right flow**, not explain why the flow exists.
Rationale, incident history, and design rationale belong in a sibling design doc
(`references/` or repo-level `docs/`). The flow itself is what Claude executes.

**Smell:** the SKILL contains long comment blocks justifying choices, T-NNN
references, "we had a bug where…", or pre/post-mortem text.
**Fix:** move the rationale to a referenced design doc; the SKILL reads as
imperative steps.

## 2. Three-level progressive disclosure

Skills use a deliberate three-level system:

| Level | What | When loaded |
|------|------|-------------|
| 1. YAML frontmatter | `name`, `description` (under 1024 chars) | Always — in system prompt |
| 2. SKILL.md body | Core instructions | When Claude decides the skill is relevant |
| 3. Linked files | `scripts/`, `references/`, `assets/` | On demand, navigated by Claude |

**Implication:** SKILL.md should stay small (guide says **under 5,000 words**).
Move detailed docs to `references/`. Move executable code to `scripts/`.
Reference them with explicit pointers like `Run scripts/launch-worktree.sh <wt>`.

## 3. Extract scripts; have the agent run them

> "For critical validations, consider bundling a script that performs the checks
> programmatically rather than relying on language instructions. Code is
> deterministic; language interpretation isn't."

Long bash blocks embedded in SKILL.md are a smell. They are:
- harder to test (no shell linting in markdown)
- harder to evolve (every edit risks heredoc/quoting drift)
- harder for Claude to execute reliably (it has to copy-paste verbatim)

**Fix:** extract them to `scripts/<verb-noun>.sh` (or `.py`). The SKILL says
"Run `scripts/foo.sh <args>` — see expected output below." Claude executes the
script as a tool call.

## 4. The description field is load-bearing

The frontmatter `description` is how Claude decides whether to load the skill.
Get this wrong and the skill never triggers (or triggers on everything).

**Structure:** `[What it does] + [When to use it] + [Key capabilities]`

**Good:**
> Manages Linear project workflows including sprint planning, task creation, and
> status tracking. Use when user mentions "sprint", "Linear tasks", "project
> planning", or asks to "create tickets".

**Bad:**
- "Helps with projects" (too vague)
- "Implements the Project entity model with hierarchical relationships." (no triggers)

**Required content:**
- Specific trigger phrases users would actually say
- File types if relevant
- Negative triggers if there's overlap with another skill ("Do NOT use for X")

## 5. File structure & naming

```
your-skill-name/
├── SKILL.md             # Required — main file
├── scripts/             # Optional — executable code
│   ├── process_data.py
│   └── validate.sh
├── references/          # Optional — documentation
│   ├── api-guide.md
│   └── examples/
└── assets/              # Optional — templates, fonts, icons
    └── report-template.md
```

- `SKILL.md` exact spelling, case-sensitive. No `skill.md`, no `SKILL.MD`.
- Folder name **kebab-case**. No spaces, underscores, or capitals.
- **No README.md inside the skill folder.** All docs live in SKILL.md or
  `references/`. (Repo-level READMEs for human visitors are fine and separate.)

## 6. SKILL.md body: be specific and actionable

**Bad:** "Validate the data before proceeding."
**Good:**
```
Run `python scripts/validate.py --input {filename}` to check data format.
If validation fails, common issues include:
- Missing required fields (add them to the CSV)
- Invalid date formats (use YYYY-MM-DD)
```

**Critical instructions go at the top.** Use `## Important` or `## Critical`
headers when something must not be missed. Repeat key points if needed.

**Avoid ambiguous language.** Replace "make sure to validate things properly"
with "CRITICAL: Before calling create_project, verify: project name non-empty,
at least one team member assigned, start date not in the past."

## 7. Reference bundled resources clearly

When SKILL.md needs to point Claude at a file, be explicit:

> Before writing queries, consult `references/api-patterns.md` for:
> - Rate limiting guidance
> - Pagination patterns
> - Error codes and handling

This signals progressive disclosure — Claude only loads `references/api-patterns.md`
when it's about to write a query.

## 8. Patterns that work

The guide names five reusable patterns; pick the one that fits before inventing a
new shape:

1. **Sequential workflow orchestration** — multi-step processes in a specific
   order, with explicit step ordering, dependencies, and rollback per stage.
2. **Multi-MCP coordination** — workflows spanning multiple services, with clear
   phase separation and validation between phases.
3. **Iterative refinement** — output quality improves with iteration; explicit
   quality criteria and a "know when to stop" rule.
4. **Context-aware tool selection** — same outcome via different tools depending
   on context; clear decision criteria, fallback options, transparency about
   the choice.
5. **Domain-specific intelligence** — embed compliance/business rules in the
   skill itself, not just tool routing.

Most cloglog plugin skills are pattern 1 or 2; the audit should classify each
existing skill against these patterns.

## 9. Common failure modes (troubleshooting checklist)

When a skill misbehaves, check:

- **Doesn't trigger** → description too vague, missing trigger phrases.
  Fix: add detail and keywords. Ask Claude "When would you use the [skill]
  skill?" — Claude will quote the description back; adjust based on what's
  missing.
- **Triggers too often** → add **negative triggers** ("Do NOT use for X"),
  be more specific, clarify scope.
- **Loads but Claude doesn't follow instructions** →
  - Instructions too verbose → keep concise, use bullets, move detail to
    `references/`.
  - Instructions buried → put critical instructions at the top, use
    `## Important` headers.
  - Ambiguous language → be explicit, use deterministic scripts where possible.
- **Slow / degraded responses** → SKILL.md too large. Move detail to
  `references/`. Aim for under 5,000 words.

## 10. Security: forbidden in frontmatter

- **No XML angle brackets** (`<` `>`) — frontmatter appears in Claude's system
  prompt; angle brackets could inject instructions.
- **No "claude" or "anthropic" in skill name** — reserved.

## 11. Eval expectation

The guide assumes every skill has at least an informal eval set:

- **Triggering tests:** 10–20 prompts that should trigger; verify they do.
  Plus prompts that should NOT trigger; verify they don't.
- **Functional tests:** valid outputs, API calls succeed, error handling works,
  edge cases covered.
- **Performance comparison:** with-skill vs. without-skill — back-and-forth
  count, failed calls, tokens consumed.

cloglog plugin skills were not authored with `skill-creator`. Coverage
splits by layer:

- **Functional layer — partially covered.** `tests/plugins/` already
  carries 30+ pytest-based pin tests that lock structural / behavioural
  invariants in the SKILLs (e.g. `test_setup_skill_dedup.py`,
  `test_launch_skill_has_agent_started_timeout.py`,
  `test_init_bootstrap_skill.py`,
  `test_close_wave_skill_lifecycle_calls.py`,
  `test_github_bot_skill_worktree_merge.py`). These are real regression
  pins, not absent — but they are not the full functional eval suite the
  guide describes (varied scenarios, edge-case explosion, with-skill vs.
  without-skill comparison).
- **Triggering layer — entirely absent.** No should-fire / should-not-fire
  prompt corpus exists for any skill's frontmatter `description`; no
  harness exercises the model's skill-selection behaviour against user
  phrasing. This is the gap §11 specifically targets.

The audit should distinguish these two layers when flagging coverage —
not blanket-claim "no eval sets." Building the trigger-prompt corpus
(and any remaining functional-layer gaps after auditing
`tests/plugins/`) is downstream follow-up work, not blocking on the
hygiene refactor.

## 12. The audit rubric (apply to every skill in plugins/cloglog/skills/)

For each skill, answer:

1. **Frontmatter quality** — does `description` follow the
   `[What] + [When] + [Capabilities]` shape with explicit trigger phrases?
   Any negative triggers needed?
2. **Body size** — is SKILL.md under 5,000 words? If not, what moves to
   `references/`?
3. **Recipe vs. research** — does the body read as imperative steps, or does
   it explain *why*? List the rationale paragraphs that should move out.
4. **Embedded scripts** — are there bash/python blocks longer than ~10 lines?
   Each one is a candidate for `scripts/<verb-noun>.sh`.
5. **Pattern fit** — which of the five patterns does this skill match? If
   none, is the shape justified?
6. **Triggering risk** — under-triggering or over-triggering? Note any
   overlap with sibling skills.
7. **Critical instructions** — are they at the top of the body, in
   `## Critical` headers? Anything important buried?
8. **Reference structure** — are `references/`, `scripts/`, `assets/` used,
   or is everything inline?
9. **README.md inside the folder?** (must not exist — flag for deletion)
10. **Follow-up tasks** — file one task per concrete fix, not a single
    "improve this skill" task.

## 13. The `skill-creator` skill exists

It is available in Claude.ai and Claude Code, and should be the default tool
for **new** skills going forward. For the existing plugin skills, the audit
+ refactor work is a one-time backfill — don't try to retroactively pipe them
through skill-creator. But: when adding a new skill to the plugin after this
backfill, use skill-creator to bootstrap.
