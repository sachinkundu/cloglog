# Plugin SKILL Hygiene Audit (F-56 / T-430)

Read-only audit of every skill under `plugins/cloglog/skills/` against the
10-point rubric in `plugins/cloglog/docs/skill-hygiene-lessons.md` §12
(distilled from *The Complete Guide to Building Skills for Claude*,
Anthropic 2025). The rubric doc is vendored into the plugin's own `docs/`
tree so installed copies of the plugin can verify the audit
self-contained, per the self-containment rule pinned by
`tests/plugins/test_plugin_docs_self_contained.py`.

Word counts from `wc -w SKILL.md`. The hygiene guide's body-size budget is
**5,000 words** — any skill above that line is a "loads but Claude doesn't
follow instructions" failure waiting to happen (§9, §6).

## Scope

Seven skills audited: `close-wave/`, `demo/`, `github-bot/`, `init/`,
`launch/`, `reconcile/`, `setup/`. Each has exactly one `SKILL.md`.
`setup/` also carries a sibling helper file at
`plugins/cloglog/skills/setup/dedup-inbox-monitor.sh` (directly under
the skill folder — there is no `scripts/` subdirectory). It is the only
**skill-local** helper across the seven; several other skills call into
**shared plugin-root scripts** under `${CLAUDE_PLUGIN_ROOT}/scripts/`
(see §D / §G below for details).

## Rubric matrix

Legend: ✅ passes · ⚠️ partial / minor issue · ❌ fails

| Skill | 1. Frontmatter | 2. Body size | 3. Recipe vs. research | 4. Embedded scripts | 5. Pattern fit | 6. Triggering risk | 7. Critical at top | 8. References used | 9. README absent | 10. Follow-ups filed |
|------|----|----|----|----|----|----|----|----|----|----|
| close-wave | ⚠️ | ✅ 3,387 | ❌ heavy T-NNN history | ❌ many >10-line bash blocks | Pattern 1 | ⚠️ overlap with reconcile delegation, no negative trigger | ✅ | ❌ none | ✅ | T-445, T-452, T-459 |
| demo | ⚠️ | ✅ 2,916 | ❌ inline rationale + gotchas | ❌ Step 0 / Step 5 templates >40 lines | Pattern 1 | ✅ user-invocable: false, called from PR flow | ⚠️ "Stop and ask" intro buries Step 0 | ❌ none | ✅ | T-446, T-453 |
| github-bot | ⚠️ | ❌ 5,164 (over 5K) | ❌ heavy T-NNN history + Codex internals | ❌ auto-merge gate invocation, push+PR templates | Pattern 1+4 (mixed) | ⚠️ broad "ALL GitHub operations" — no negative trigger | ✅ | ❌ none | ✅ | T-447, T-454, T-460 |
| init | ⚠️ | ❌ 6,554 (over 5K) | ❌ extensive T-NNN history + Python merge inline | ❌ Step 2 phase-1 detection ~70 lines, Step 3 merge ~60 lines, Step 4b stack templates | Pattern 1 | ✅ user-invocable, single trigger phrase | ✅ | ❌ none | ✅ | T-448, T-455, T-461 |
| launch | ⚠️ | ✅ 3,387 | ❌ T-NNN refs (T-353/T-354/T-360/T-384/T-437/T-348) | ⚠️ Step 4e shell + render_template invocation OK, but inline | Pattern 2 (multi-step lifecycle) | ✅ explicit `F-*`/`T-*` trigger | ✅ | ⚠️ delegates rationale to `docs/launch-design.md` (good!) but still inlines T-NNN | ✅ | T-354 (done) shipped the structural refactor (heredoc→Jinja2, recipe-shape, scripts/). T-431 was filed earlier this session as launch-refactor scaffolding (per 2026-05-05 work log) but is not currently board-visible. T-449 supersedes T-431's hygiene scope by filing the residual T-NNN-marker sweep on top of T-354's done baseline. |
| reconcile | ⚠️ | ✅ 2,582 | ❌ Case-classification rationale + T-270/T-371/T-374/T-395 history | ❌ Step 5.0 predicate explanation reads as essay | Pattern 1 | ✅ explicit invocation | ✅ | ❌ none | ✅ | T-450, T-456 |
| setup | ⚠️ | ✅ 1,898 | ⚠️ T-294/T-419 history embedded, but tighter | ✅ skill-local helper already extracted (`dedup-inbox-monitor.sh`, directly under the skill folder, no `scripts/` subdir) | Pattern 1 | ⚠️ broad description (overlaps with init for "session start"); no negative trigger | ✅ | ⚠️ has skill-local helper file, no `references/` and no `scripts/` subdirectory | ✅ | T-451, T-457 |

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

**Every audited SKILL violates this.** Distinct `T-NNN` / `B-NNN`
markers per body, regenerated by
`grep -oE 'T-[0-9]+' plugins/cloglog/skills/<skill>/SKILL.md | sort -u`
(plus an explicit `B-` grep) on the SHA being audited:

- `close-wave`: T-217, T-244, T-270, T-329, T-339, T-352, T-368, T-371,
  T-395, plus B-2 → 10 distinct markers
- `demo`: T-316 → 1
- `github-bot`: T-262, T-295, T-329, T-348, T-362, T-424, T-438 → 7
- `init`: T-214, T-316, T-321, T-344, T-346, T-348, T-382, T-387, T-398
  → 9 (note: many appear repeatedly across the body — T-382/T-398 each
  cluster around the per-project credential resolver)
- `launch`: T-332, T-348, T-353, T-354, T-356, T-360, T-378, T-384,
  T-437 → 9 (T-45 / T-46 also appear, but those are example task numbers
  inside the SKILL's `Usage` block, not incident references)
- `reconcile`: T-218, T-268, T-270, T-339, T-355, T-357, T-359, T-361,
  T-364, T-366, T-368, T-369, T-371, T-395 → 14 (the 2026-04 stale
  close-off cohort — T-355 / T-357 / T-359 / T-361 / T-364 / T-366 /
  T-369 — accounts for half of these and is a single rationale cluster
  worth moving as one block)
- `setup`: T-294, T-356, T-374, T-419 → 4

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

Two extraction shapes are already in use across the plugin and are
**both valid**:

- **Skill-local helper** — a script (or `scripts/` subdirectory) directly
  under the skill folder. `setup/` ships `dedup-inbox-monitor.sh`
  alongside its `SKILL.md`. This is the shape the guide §3 documents
  most directly.
- **Shared plugin-root script** — a helper under
  `${CLAUDE_PLUGIN_ROOT}/scripts/` invoked by multiple skills. Already
  widely used: `launch/SKILL.md` calls
  `${CLAUDE_PLUGIN_ROOT}/scripts/render_template.py`; `github-bot/SKILL.md`
  calls `${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py`;
  `reconcile/SKILL.md` and `close-wave/SKILL.md` both call
  `${CLAUDE_PLUGIN_ROOT}/scripts/wait_for_agent_unregistered.py`. The
  pattern itself is pinned by
  `tests/plugins/test_skills_use_plugin_root_scripts.py`.

So the gap surfaced by this audit is **not** "no skill ever extracts" —
several do, via the shared `${CLAUDE_PLUGIN_ROOT}/scripts/` pattern. The
gap is "long bash blocks still inline in SKILL.md bodies even though the
extraction infrastructure is right there." Worst offenders by
embedded-block size:

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

**No skill uses `references/`.** Only `setup/` ships a skill-local helper
file (`dedup-inbox-monitor.sh`, directly under the skill folder; not a
`scripts/` subdirectory). Six skills have nothing under their folder
except `SKILL.md`. Several skills do call **shared** plugin-root scripts
under `${CLAUDE_PLUGIN_ROOT}/scripts/` (launch → `render_template.py`,
github-bot → `gh-app-token.py`, reconcile + close-wave →
`wait_for_agent_unregistered.py`), so the extraction precedent is
already established at the plugin level — the per-skill local
`scripts/` and `references/` directories are simply absent. Every "move
rationale out" follow-up below should land in `references/<topic>.md`
per the guide's §7 layout. Follow-ups extracting bash blocks may use
either the skill-local `scripts/` shape or contribute to the shared
plugin-root `scripts/` directory, picked per script reusability.

### H. README absence (rubric §9)

No skill has a `README.md` inside its folder. ✅ across the board.

### I. Eval sets (rubric §11)

The guide expects every skill to ship with **two** layers of eval coverage:
(1) trigger tests — 10–20 prompts that should fire, plus prompts that
should NOT, exercising the skill's `description` field via real model
behaviour; and (2) functional tests — valid outputs, error handling,
edge cases.

**Functional layer: partially covered.** `tests/plugins/` carries 30+
pytest-based pin tests that lock structural and behavioural invariants in
the SKILLs themselves. Sample coverage:

- `test_setup_skill_dedup.py` — pins the `dedup-inbox-monitor.sh` helper's
  three exit-code contracts plus its referencing in `setup/SKILL.md`.
- `test_launch_skill_has_agent_started_timeout.py` — pins the launch
  SKILL's confirmation-deadline contract.
- `test_init_bootstrap_skill.py` / `test_init_mints_per_project_credentials.py`
  / `test_init_repo_url_backfill.py` — pin init's bootstrap detection,
  per-project credentials, and `repo_url` backfill.
- `test_close_wave_skill_lifecycle_calls.py` /
  `test_close_wave_skill_no_detached_push.py` — pin close-wave's MCP-call
  ordering and bot-token-only push paths.
- `test_github_bot_skill_worktree_merge.py` — pins github-bot's
  worktree-aware `gh pr merge` flag handling.
- `test_enforce_inbox_monitor_hook.py`,
  `test_auto_merge_skill_handles_silent_holds.py`, etc.

These cover **structural invariants and behavioural pins** the skills
must obey — they are real functional regression coverage, not absent.
What they are **not** is a full functional eval suite per the guide
(varied input scenarios, edge-case explosion, performance comparison
with-skill vs. without-skill).

**Trigger layer: entirely absent.** No corpus of "should-fire" /
"should-not-fire" prompts exists for any of the seven skills' frontmatter
`description` fields. There is no harness that exercises the model's
skill-selection behaviour in response to user phrasing. This is the gap
the guide §11 specifically calls out.

The downstream-feature proposal (T-458) is therefore narrowed: build the
**trigger-prompt eval corpus** (and round out the functional eval beyond
the pin-test layer where gaps remain — to be surveyed under that feature),
not "build evals from scratch as if pin tests don't exist." A correctly
scoped task list under that feature will audit `tests/plugins/` first
to identify which skills already have functional pins and which still
need them, then layer trigger-prompt suites on top.

## Per-skill summary

### close-wave
- ❌ T-NNN/incident history scattered across Steps 1–13: T-217, T-244,
  T-270, T-329, T-339, T-352, T-368, T-371, T-395, B-2. Move to
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
- ❌ T-NNN history (T-262, T-295, T-329, T-348, T-362, T-424, T-438)
  inline. Move to `references/github-bot-history.md` (T-447).
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
- ❌ T-NNN history (T-214, T-316, T-321, T-344, T-346, T-348, T-382,
  T-387, T-398) inline; T-382 / T-398 each appear repeatedly across
  the per-project-credential resolver sections and should move as a
  single block. Move to `references/init-history.md` (T-448).
- ❌ Step 2 phase-1 (~70 line bash detection block), Step 3 Python merge
  (~60 lines), Step 6a canonicalize URL — extract to
  `scripts/detect-bootstrap-phase.sh`, `scripts/merge-mcp-config.py`,
  `scripts/canonicalize-repo-url.sh` (T-461).

### launch
- ❌ T-NNN markers (T-332, T-348, T-353, T-354, T-356, T-360, T-378,
  T-384, T-437) inline despite design doc existing.
  Audit each marker — promote to `docs/launch-design.md` if not already
  there, then drop the inline ref (T-449). **NB on prior refactor history:**
  there are two recorded prior launch-refactor tasks. **T-354** (now
  `done`, "Refactor launch SKILL — extract scripts, recipe-shape SKILL.md,
  deterministic templating (drop heredoc+sed)") shipped the structural
  refactor (heredoc→Jinja2 via T-437 follow-up, render_template.py,
  AGENT_PROMPT.md template). **T-431** appears in
  `docs/work-logs/2026-05-05-t394-mcp-position-reorder-work-log.md` as
  "launch refactor" scaffolding filed under F-56 in that session, with
  `wait-for-agent-started.sh` listed among its planned extractions.
  As of this audit, `mcp__cloglog__search T-431` returns no row — the
  task is not visible to the board API today. Treat the work-log entry
  as the authoritative record that scaffolding existed; the residual
  T-NNN-marker sweep this audit identifies is filed under **T-449**,
  which **supersedes** T-431's launch-hygiene scope. If T-431 turns
  out to still be a live row hidden behind a search bug, fold it into
  T-449 (or vice-versa) before starting work — do not run two parallel
  launch-hygiene refactors. T-449 builds on T-354's done baseline; do
  not redo T-354's structural work.

### reconcile
- ❌ Case A/B/C rationale reads as essay rather than recipe; T-NNN
  history inline: T-218, T-268, T-270, T-339, T-368, T-371, T-395, plus
  the 2026-04 stale-close-off cohort T-355 / T-357 / T-359 / T-361 /
  T-364 / T-366 / T-369 (one rationale cluster, move as a block). Move
  to `references/reconcile-cases.md` (T-450).
- ❌ Step 5.0 predicate explanation occupies ~70 lines. Extract the
  three-component check to `scripts/check-completed-cleanly.sh` and
  reduce SKILL prose to "Run …; on rc=0 delegate to close-wave" (T-456).

### setup
- ✅ Already ships a skill-local helper at
  `plugins/cloglog/skills/setup/dedup-inbox-monitor.sh` (directly under
  the skill folder — there is no `scripts/` subdirectory; if directory
  shape per the guide §5 matters to a follow-up, that's a no-op move).
  Body is the smallest at 1,898w.
- ⚠️ T-294 / T-356 / T-374 / T-419 markers inline. Light prune to
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
| T-458 | downstream feature proposal | Narrowed: propose feature for **trigger-prompt eval corpus** (functional pin coverage already partially exists under `tests/plugins/`) | Eval sets |
| T-459 | close-wave | Add negative trigger vs reconcile delegation | Frontmatter |
| T-460 | github-bot | Add negative trigger ("Do NOT use for read-only operator-invoked gh commands") | Frontmatter |
| T-461 | init | Extract phase-1 detection + Python merge + URL canonicalize → `scripts/` | Embedded scripts |

## Methodology notes

- Word counts via `wc -w plugins/cloglog/skills/*/SKILL.md`.
- T-NNN density estimated by `grep -oE 'T-[0-9]+'` per body — exact counts
  vary; orders of magnitude given.
- No SKILL files were modified by this audit. Read-only per scope.
- Audit author: T-430 worktree agent, 2026-05-05.
