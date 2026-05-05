# Wave: reconcile-wt-t467-demo-exemption-jinja2

**Date:** 2026-05-05
**Worktree:** wt-t467-demo-exemption-jinja2
**PR:** [#332](https://github.com/sachinkundu/cloglog/pull/332) — `feat(T-467): jinja2-render demo exemption.md + harden check-demo.sh frontmatter gate`
**Invoked from:** reconcile (close-wave delegation, predicate held)

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t467-demo-exemption-jinja2 | cooperative (tier 1) | 1 | T-475 regression: tab closed via helper. Codex `:pass:` first round. |

## Commits

```
08d8e38 feat(T-467): jinja2-render demo exemption.md + harden check-demo.sh frontmatter gate
```

## Files changed

- `plugins/cloglog/templates/exemption.md.template` (new — Jinja2)
- `plugins/cloglog/skills/demo/SKILL.md` — heredoc → `render_template.py` call
- `scripts/check-demo.sh` — hardened to require all four frontmatter keys
- `tests/test_exemption_template.py` (new — 7 pin tests)
- `tests/test_check_demo_exemption_hash.py` — assertion update
- `docs/invariants.md` — two new invariant entries
- `docs/design/templating-modernization.md` — row #12 marked done

## Per-task work log (from `work-log-T-467.md`)

### What was done

1. **Shell injection risk eliminated.** Replaced unquoted heredoc in
   `demo/SKILL.md:124-145` with a Jinja2 template rendered by
   `render_template.py`. Classifier `reasoning` field (free-form prose
   with backticks / `$()`) is now safe.
2. **`check-demo.sh` hardened.** Per-field validation for `verdict`,
   `diff_hash`, `classifier`, `generated_at` (was: only `diff_hash`).
   Refactored extraction into a reusable `_extract_fm_field()` helper.

### Decisions
- `_extract_fm_field()` helper reuses the existing awk fence-counting
  logic (single source of truth, no duplicated awk per field).
- Field check order: `verdict` first → most diagnostic name surfaces if
  template is wholly broken.
- `render_template.py` invoked via `uv run --with jinja2` per the
  existing pattern — no system-level Jinja2 dep.

### Codex review
Session 1/5: `:pass:`. CI: all 3 checks green.

### Test delta
6 → 13 tests. `make quality` passes.

## Learnings & Issues

### Routing

- **Two new entries already routed to `docs/invariants.md`** by the agent
  in this PR — the agent did the routing inline rather than leaving it
  for close-wave Step 11. This is the correct shape: invariants are
  pin-test-backed, and this task added the pins.
- **`check-demo.sh` per-field validation does NOT check field values
  (e.g., `verdict == no_demo`).** That would require YAML parsing
  which conflicts with the hooks-grep+sed invariant
  (`docs/invariants.md` "hook YAML parsing"). If value validation is
  needed, it would be a separate task using Python — not warranted
  today.
- **Heredoc → Jinja2 pattern is the canonical migration shape**
  (T-354/T-437/T-467). Already documented in
  `docs/design/templating-modernization.md`.

### Bug observed (cross-wave): T-475 exit-on-unregister regression
Same survival pattern. Already filed.

### Quality gate
Passed on main after fast-forward.

## State after this wave

- Demo exemption flow is now safe against backtick/`$()` injection in
  classifier reasoning.
- `check-demo.sh` rejects exemptions missing any of the four required
  frontmatter keys with a clear per-field message.
- `docs/design/templating-modernization.md` row #12 → done.
- Remaining F-58 expedite-class work: T-468 (lifecycle JSON event helper)
  is the next-most-urgent.
