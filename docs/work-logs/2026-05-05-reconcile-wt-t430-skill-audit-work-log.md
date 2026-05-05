# Wave: reconcile-wt-t430-skill-audit

**Date:** 2026-05-05
**Worktree:** wt-t430-skill-audit
**PR:** [#328](https://github.com/sachinkundu/cloglog/pull/328) — `docs(plugin): T-430 audit cloglog skills against hygiene rubric`
**Invoked from:** reconcile (close-wave delegation, predicate held)

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t430-skill-audit | cooperative (tier 1) | 4 | exit-on-unregister hook did NOT terminate launcher (T-475); tab closed via helper |

## Commits

```
149f06c docs(plugin): T-430 address codex round-3 — accurate T-marker inventory + vendored-rubric eval framing
947f187 docs(plugin): T-430 address codex round-2 — vendor rubric, fix paths and refactor history
e0486df docs(plugin): T-430 address codex round-1 — clarify launch refactor history + eval coverage state
e9c8d24 docs(plugin): T-430 audit cloglog skills against hygiene rubric
```

## Files changed

- `plugins/cloglog/docs/skill-audit.md` (new — per-skill × rubric matrix)
- `plugins/cloglog/docs/skill-hygiene-lessons.md` (new — vendored rubric)

## Per-task work log (from `work-log-T-430.md`)

### What shipped
A read-only hygiene audit of all 7 cloglog plugin skills (close-wave, demo,
github-bot, init, launch, reconcile, setup) scored against the 10-point rubric
in *The Complete Guide to Building Skills for Claude* (Anthropic, 2025),
distilled into `skill-hygiene-lessons.md`. Two new docs and 17 follow-up tasks
filed under F-56.

### Decisions
- **17 follow-up tasks instead of bundling.** Rubric §10 forbids "improve this
  skill" mega-tasks. T-445..T-461 each one PR's worth of work.
- **Eval-coverage finding scoped narrowly.** Distinguished partially-covered
  functional layer (30+ pin tests under `tests/plugins/`) from entirely-absent
  triggering layer. T-458 targets only the triggering layer.
- **Launch history reconciled.** T-354 (done) shipped the structural launch
  refactor. T-431 appears in old work log but `search` returns no row; T-449
  treated as canonical superseder.

### Codex review
4 rounds. Round 1: launch refactor history, blanket "no eval sets" claim.
Round 2: T-431 framing, setup script path, shared-script extraction shape,
rubric not vendored. Round 3: vendored rubric §11 mirroring, T-NNN inventory
inaccuracy. Round 4: `:pass:`.

### Learnings (routed)

These are routed below to their proper homes per Step 11.

## Learnings & Issues

### Routing

- **Verify factual claims by running `grep` against live files, not memory.**
  Audit-class learning — applies to any audit/sweep task. Adding to the
  audit's own methodology section in `plugins/cloglog/docs/skill-audit.md`
  would make sense, but that's an in-document concern, not cross-cutting.
  Dropped — captured in the audit doc itself.
- **Self-containment rule for vendored plugin docs.** Already pinned by
  `tests/plugins/test_plugin_docs_self_contained.py`. No new home needed.
- **Two extraction shapes coexist (skill-local helpers vs. shared plugin-root
  scripts).** Already pinned by
  `tests/plugins/test_skills_use_plugin_root_scripts.py`. No new home needed.
- **Functional eval coverage already exists.** Captured in T-458's filed task
  body; no separate home needed.

No new entries to `docs/invariants.md`, SKILL files, or design docs are
warranted from this audit. The 17 filed follow-up tasks ARE the routed
output.

### Bug observed (cross-wave): T-475 exit-on-unregister regression

Same symptom as the wt-t432 close-wave: launcher + claude survived past
`agent_unregistered` for 4+ minutes; `/tmp/agent-shutdown-debug.log` had no
entries. Workaround: `close-zellij-tab.sh wt-t430-skill-audit`. Already filed
as T-475.

### Quality gate
Passed on main after fast-forward.

## State after this wave

- `plugins/cloglog/docs/skill-audit.md` is the canonical hygiene-state record
  for the 7 plugin skills.
- T-445..T-461 are the prioritized follow-up roadmap under F-56 (Plugin
  SKILL Hygiene).
- T-449 supersedes T-431 (which is missing from the board) for launch-skill
  hygiene work.
