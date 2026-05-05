# Plugin SKILL Hygiene Audit (F-56 / T-430)

Read-only audit of every skill under `plugins/cloglog/skills/` against the
10-point rubric in `skill-hygiene-lessons.md` §12 (distilled from
*The Complete Guide to Building Skills for Claude*, Anthropic 2025).

Word counts from `wc -w SKILL.md`. The hygiene guide's body-size budget is
**5,000 words** — any skill above that line is a "loads but Claude doesn't
follow instructions" failure waiting to happen (§9, §6).

## Scope

Seven skills audited: `close-wave/`, `demo/`, `github-bot/`, `init/`,
`launch/`, `reconcile/`, `setup/`. Each has exactly one `SKILL.md`, with
`setup/` also carrying a sibling `scripts/dedup-inbox-monitor.sh`.

## Rubric matrix

Legend: ✅ passes · ⚠️ partial / minor issue · ❌ fails

| Skill | 1. Frontmatter | 2. Body size | 3. Recipe vs. research | 4. Embedded scripts | 5. Pattern fit | 6. Triggering risk | 7. Critical at top | 8. References used | 9. README absent | 10. Follow-ups filed |
|------|----|----|----|----|----|----|----|----|----|----|
| close-wave | ⚠️ | ✅ 3,387 | ❌ heavy T-NNN history | ❌ many >10-line bash blocks | Pattern 1 | ⚠️ overlap with reconcile delegation, no negative trigger | ✅ | ❌ none | ✅ | T-445, T-452, T-459 |
| demo | ⚠️ | ✅ 2,916 | ❌ inline rationale + gotchas | ❌ Step 0 / Step 5 templates >40 lines | Pattern 1 | ✅ user-invocable: false, called from PR flow | ⚠️ "Stop and ask" intro buries Step 0 | ❌ none | ✅ | T-446, T-453 |
| github-bot | ⚠️ | ❌ 5,164 (over 5K) | ❌ heavy T-NNN history + Codex internals | ❌ auto-merge gate invocation, push+PR templates | Pattern 1+4 (mixed) | ⚠️ broad "ALL GitHub operations" — no negative trigger | ✅ | ❌ none | ✅ | T-447, T-454, T-460 |
| init | ⚠️ | ❌ 6,554 (over 5K) | ❌ extensive T-NNN history + Python merge inline | ❌ Step 2 phase-1 detection ~70 lines, Step 3 merge ~60 lines, Step 4b stack templates | Pattern 1 | ✅ user-invocable, single trigger phrase | ✅ | ❌ none | ✅ | T-448, T-455, T-461 |
| launch | ⚠️ | ✅ 3,387 | ❌ T-NNN refs (T-353/T-354/T-360/T-384/T-437/T-348) | ⚠️ Step 4e shell + render_template invocation OK, but inline | Pattern 2 (multi-step lifecycle) | ✅ explicit `F-*`/`T-*` trigger | ✅ | ⚠️ delegates rationale to `docs/launch-design.md` (good!) but still inlines T-NNN | ✅ | task description claims sibling refactor task exists — **it does not** (F-56 had only T-430). T-449 files it now. |
| reconcile | ⚠️ | ✅ 2,582 | ❌ Case-classification rationale + T-270/T-371/T-374/T-395 history | ❌ Step 5.0 predicate explanation reads as essay | Pattern 1 | ✅ explicit invocation | ✅ | ❌ none | ✅ | T-450, T-456 |
| setup | ⚠️ | ✅ 1,898 | ⚠️ T-294/T-419 history embedded, but tighter | ✅ already extracted dedup helper to `scripts/` (only skill that does!) | Pattern 1 | ⚠️ broad description (overlaps with init for "session start"); no negative trigger | ✅ | ⚠️ has `scripts/`, no `references/` | ✅ | T-451, T-457 |

## Cross-cutting findings

### A. Frontmatter quality (rubric §1)

All seven `description` fields read like one-liner summaries rather than the
**[What] + [When] + [Capabilities]** shape from the guide. Trigger phrases
are present in some (`setup` enumerates "which monitor are you watching",
"show inbox", etc. — model behaviour) but **none carry negative triggers**.
Most likely-to-misfire pairs:

- `setup` vs `init` — both fire on "session start" / "configure cloglog". `setup`
  needs a "Do NOT use for first-time project bootstrap (use init)" line.
- `close-wave` vs `reconcile` — overlap on "tear down a worktree". `close-wave`
  needs "Do NOT use to fix orphaned worktrees mid-flight (use reconcile)" and
  vice-versa.
- `github-bot` "ALL GitHub operations" is correct as written but very broad
  — would benefit from a "Do NOT use for read-only `gh` commands the user
  invoked directly" qualifier.

No frontmatter contains `<` / `>` (§10 security check passes).
No skill name contains "claude" or "anthropic" (§10 reserved-name check passes).

### B. Body size (rubric §2)

Two skills are over the 5,000-word ceiling: `github-bot` (5,164) and `init`
(6,554). Both should move detail to `references/`:

- `github-bot` — auto-merge gate body, CI failure recovery details, gotcha
  catalogue, PR-event payload shapes. Core SKILL keeps push/PR + token-mgmt
  + event-routing decisions.
- `init` — Step 2 phase-1 detection prose, auto-repair migration logic,
  Step 4b per-stack templates (`Python with uv`, `Python without uv`,
  `Node.js`, `Rust`, `Go`, `Java/Maven`, `Java/Gradle`, `Ruby`). Move stack
  templates to `references/stack-bootstrap-templates/`.

### C. Recipe vs. research (rubric §3) — the dominant smell

**Every audited SKILL violates this.** Counts of `T-NNN` / `B-NNN`
incident-marker references in each body (rough grep):

- `close-wave`: T-217, T-244, T-262, T-270, T-329, T-339, T-352, T-368,
  T-371, T-395, B-2 → ~14 markers across rationale paragraphs
- `demo`: T-316 → 1
- `github-bot`: T-262, T-295, T-329, T-348, T-362, T-424, T-438 → ~12
- `init`: T-214, T-316, T-321, T-344, T-346, T-348, T-378, T-382, T-387,
  T-398, T-419 → ~20+
- `launch`: T-329, T-332, T-348, T-353, T-354, T-356, T-360, T-378,
  T-384, T-387, T-419, T-437 → ~15
- `reconcile`: T-218, T-270, T-329, T-339, T-368, T-371, T-374, T-378,
  T-395 → ~12
- `setup`: T-294, T-374, T-408, T-419 → ~5

The guide is explicit (§1): "SKILL.md should encode the right flow, not
explain why the flow exists. Rationale, incident history, and design
rationale belong in a sibling design doc."

`launch/SKILL.md` already does this *partially* — it points at
`${CLAUDE_PLUGIN_ROOT}/docs/launch-design.md` for "rationale and history" —
yet still inlines a dozen T-NNN markers in step bodies. That is the right
pattern; it just hasn't been finished. Apply it to the other six.

### D. Embedded scripts (rubric §4)

The guide is firm (§3): "Long bash blocks embedded in SKILL.md are a smell.
Extract them to `scripts/<verb-noun>.sh`. The SKILL says
'Run scripts/foo.sh `<args>` — see expected output below.'"

`setup/` is the only skill that follows this rule (`dedup-inbox-monitor.sh`).
Worst offenders by embedded-block size:

- `init` — Step 2 phase-1 detection bash (~70 lines), Step 3 Python merge
  (~60 lines), Step 4b stack templates (8 separate ~5-line bash blocks),
  Step 6a canonicalize-URL block. Total: ~250 inline shell/python lines.
- `github-bot` — Push+Create PR template (~40 lines), Auto-Merge gate
  invocation (~80 lines including jq/python pipeline), CI Failure Recovery
  (~10), Reply to Review Comments (~15). Total: ~150 inline lines.
- `close-wave` — Step 5a (~25), Step 5b (~10), Step 5c (~15),
  Step 5d artifact consolidation, Step 13 push-with-retry (~30). Total: ~100
  inline lines.
- `demo` — Step 0 fast-path (~25), Step 5 backend demo-script template
  (~50), Step 5 frontend demo-script template (~40). Total: ~120 inline lines.
- `launch` — Step 3 render_template.py invocation (~25), Step 4e new-tab
  + go-to-tab chain (~35). Total: ~60 inline lines.
- `reconcile` — already references `wait_for_agent_unregistered.py` as a
  script (good) but still inlines tier-1/tier-2 block + canonical-URL
  computation. Total: ~40 inline lines.

### E. Pattern fit (rubric §8)

All seven map cleanly to **Pattern 1: Sequential workflow orchestration**
(multi-step processes in a specific order). `github-bot` blends Pattern 1
with **Pattern 4: Context-aware tool selection** for the auto-merge gate
(different paths per hold reason). No skill is mis-shaped relative to the
guide; the issue is execution, not pattern selection.

### F. Critical-instructions placement (rubric §7)

Every skill puts its critical instructions in numbered Steps near the top.
`demo` is the one slight miss — Steps 0 and 1 are the gating decisions but
the body opens with a 15-line "three terminal states" overview that delays
the user from running Step 0. Minor.

### G. Reference structure (rubric §8)

**No skill uses `references/`.** Only `setup/` uses `scripts/`. Six skills
have nothing under their folder except `SKILL.md`. Every "move rationale
out" follow-up below should land in `references/<topic>.md` per the guide's
§7 layout.

### H. README absence (rubric §9)

No skill has a `README.md` inside its folder. ✅ across the board.

### I. Eval sets (rubric §11)

**No skill has eval sets.** The guide expects every skill to ship with
trigger tests (10–20 prompts that should/shouldn't fire) and functional
tests. Building these for the seven cloglog skills is downstream work — it
is in the audit's out-of-scope clause and should be a separate downstream
feature, not a hygiene-refactor task. **Filed as T-460** (downstream
feature proposal).

## Per-skill summary

### close-wave
- ❌ T-NNN/incident history scattered across Steps 1–13. Move to
  `references/close-wave-history.md` (T-445).
- ❌ ~100 inline shell lines across cooperative-shutdown sequence. Extract
  to `scripts/cooperative-shutdown.sh` + `scripts/wave-fold-commit.sh`
  (T-452).
- ⚠️ description lacks negative trigger vs. reconcile delegation
  (T-459).

### demo
- ❌ Inline rationale (gotchas section, "Determinism" essay, "Demo proof
  gotchas", "Demo-classifier allowlist"). Move to
  `references/demo-gotchas.md` (T-446).
- ❌ Step 0 / Step 5 templates inline. Extract Step 0 to
  `scripts/static-demo-exempt.sh` and ship Step 5 templates as
  `assets/demo-script-backend.sh.template` /
  `assets/demo-script-frontend.sh.template` (T-453).

### github-bot
- ❌ Body size 5,164 words — over 5,000. Reduces with refactor below.
- ❌ T-NNN history (T-262, T-295, T-348, T-362, T-424, T-438) inline.
  Move to `references/github-bot-history.md` (T-447).
- ❌ Push+Create PR template, Auto-Merge gate jq/python invocation, CI
  Failure Recovery — all multi-line bash. Extract to
  `scripts/push-and-create-pr.sh`, `scripts/run-auto-merge-gate.sh`,
  `scripts/dump-failed-ci-logs.sh` (T-454).
- ⚠️ description "ALL GitHub operations" benefits from a negative
  trigger for read-only operator-invoked `gh` commands (T-460).

### init
- ❌ Body size 6,554 words — far over 5,000. Reduce by moving Step 4b
  stack templates to `references/stack-bootstrap-templates/` (one file per
  stack) (T-455).
- ❌ T-NNN history (T-214, T-316, T-321, T-344, T-346, T-348, T-378,
  T-382, T-387, T-398, T-419) inline. Move to
  `references/init-history.md` (T-448).
- ❌ Step 2 phase-1 (~70 line bash detection block), Step 3 Python merge
  (~60 lines), Step 6a canonicalize URL — extract to
  `scripts/detect-bootstrap-phase.sh`, `scripts/merge-mcp-config.py`,
  `scripts/canonicalize-repo-url.sh` (T-461).

### launch
- ❌ T-NNN markers (T-353, T-354, T-360, T-378, T-384, T-387, T-437,
  T-419, T-348, T-332, T-329, T-356) inline despite design doc existing.
  Audit each marker — promote to `docs/launch-design.md` if not already
  there, then drop the inline ref (T-449). **NB:** task T-430's
  description claimed a launch-skill refactor task already existed under
  F-56; verified via `mcp__cloglog__list_features` /
  `get_backlog` — F-56 had only T-430. T-449 files the refactor now.

### reconcile
- ❌ Case A/B/C rationale reads as essay rather than recipe; T-NNN
  history (T-218, T-270, T-339, T-368, T-371, T-374, T-378, T-395)
  inline. Move to `references/reconcile-cases.md` (T-450).
- ❌ Step 5.0 predicate explanation occupies ~70 lines. Extract the
  three-component check to `scripts/check-completed-cleanly.sh` and
  reduce SKILL prose to "Run …; on rc=0 delegate to close-wave" (T-456).

### setup
- ✅ Already extracts `dedup-inbox-monitor.sh` (gold-standard for the
  rubric). Body is the smallest at 1,898w.
- ⚠️ T-294/T-374/T-408/T-419 markers inline. Light prune to
  `references/setup-history.md` (T-451).
- ⚠️ description triggers are explicit but lack negative trigger vs.
  `init` ("Do NOT use for first-time project bootstrap"). Add it (T-457).

## Filed follow-up tasks

All filed under F-56 (Plugin SKILL Hygiene). Each is one PR's worth of work.

| Task | Skill | Concern | Class |
|------|-------|---------|-------|
| T-445 | close-wave | Move T-NNN history → `references/close-wave-history.md` | Recipe vs research |
| T-446 | demo | Move gotchas/determinism/allowlist essays → `references/demo-gotchas.md` | Recipe vs research |
| T-447 | github-bot | Move T-NNN history → `references/github-bot-history.md` | Recipe vs research |
| T-448 | init | Move T-NNN history → `references/init-history.md` | Recipe vs research |
| T-449 | launch | Sweep inline T-NNN markers; delegate to `docs/launch-design.md` | Recipe vs research |
| T-450 | reconcile | Case A/B/C rationale → `references/reconcile-cases.md` | Recipe vs research |
| T-451 | setup | Light history prune → `references/setup-history.md` | Recipe vs research |
| T-452 | close-wave | Extract cooperative-shutdown + wave-fold-commit shell → `scripts/` | Embedded scripts |
| T-453 | demo | Extract Step 0 fast-path → `scripts/`; Step 5 templates → `assets/` | Embedded scripts |
| T-454 | github-bot | Extract push-and-create-pr + auto-merge gate wrapper + CI dump → `scripts/` | Embedded scripts |
| T-455 | init | Move Step 4b stack templates → `references/stack-bootstrap-templates/` | Body size |
| T-456 | reconcile | Extract completed-cleanly predicate → `scripts/check-completed-cleanly.sh` | Embedded scripts |
| T-457 | setup | Add negative trigger to description (Do NOT use for /cloglog init scope) | Frontmatter |
| T-458 | downstream feature proposal | Propose new feature: build eval sets for cloglog plugin skills (skill-creator-driven) | Eval sets |
| T-459 | close-wave | Add negative trigger vs reconcile delegation | Frontmatter |
| T-460 | github-bot | Add negative trigger ("Do NOT use for read-only operator-invoked gh commands") | Frontmatter |
| T-461 | init | Extract phase-1 detection + Python merge + URL canonicalize → `scripts/` | Embedded scripts |

## Methodology notes

- Word counts via `wc -w plugins/cloglog/skills/*/SKILL.md`.
- T-NNN density estimated by `grep -oE 'T-[0-9]+'` per body — exact counts
  vary; orders of magnitude given.
- No SKILL files were modified by this audit. Read-only per scope.
- Audit author: T-430 worktree agent, 2026-05-05.
