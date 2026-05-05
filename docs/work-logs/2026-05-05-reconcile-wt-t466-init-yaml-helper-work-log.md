# Wave: reconcile-wt-t466-init-yaml-helper

**Date:** 2026-05-05
**Worktree:** wt-t466-init-yaml-helper
**PR:** [#331](https://github.com/sachinkundu/cloglog/pull/331) — `feat(T-466): replace sed-i config.yaml updates with Python YAML helper`
**Invoked from:** reconcile (close-wave delegation, predicate held)

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t466-init-yaml-helper | cooperative (tier 1) | 2 | T-475 regression: tab closed via helper |

## Commits

```
abefccc fix(T-466): guard trailing newline on append; make docs self-contained
4917ff8 feat(T-466): replace sed-i config.yaml updates with Python YAML helper
```

## Files changed

- `plugins/cloglog/scripts/set_yaml_keys.py` — new stdlib helper
- `plugins/cloglog/skills/init/SKILL.md` — Step 4 bash block replaced
- `plugins/cloglog/docs/setup-credentials.md` — Step 4 docs section replaced
- `tests/plugins/test_init_yaml_helper.py` — 18 pin tests

## Per-task work log (from `work-log-T-466.md`)

### What was done
Replaced three `sed -i "s/^KEY:.*/KEY: ${VAR}/"` substitutions in
`plugins/cloglog/skills/init/SKILL.md:310-329` with a stdlib-only Python
helper that upserts scalar keys safely. Mirrored the replacement in the
operator-facing doc.

### Key decisions
- **Stdlib-only** — no PyYAML, per `docs/invariants.md:76` portability
  constraint.
- **Line-by-line regex** with full Python string ops avoids sed
  delimiter escaping entirely.
- **Atomic write** via `.tmp` → `replace()`.
- **Two invocation forms by context.** SKILL.md uses
  `${CLAUDE_PLUGIN_ROOT}/scripts/set_yaml_keys.py` (runs inside Claude
  Code). `setup-credentials.md` uses an inline `python3 - <<'PY'` heredoc
  because the operator-facing doc must work in a plain shell where
  `CLAUDE_PLUGIN_ROOT` is unset.

### Codex review
- **Session 1 (`:warning:`):** Trailing-newline bug (appended key glued
  to last line of a file with no final `\n`); `${CLAUDE_PLUGIN_ROOT}` in
  setup-credentials.md unusable outside Claude Code.
- **Session 2 (`:pass:`):** Both findings resolved. Auto-merge gate
  passed.

## Learnings & Issues

### Routing

- **Inline-heredoc duplicate of helper logic in `setup-credentials.md`.**
  T-466's resolution required two implementations of the same
  upsert algorithm — one importable, one inline for plain-shell
  operators. Worth noting in `setup-credentials.md` itself with a
  comment pointing at the canonical helper. Captured as a residual TODO
  in the per-task log; not a routed learning yet.
- **Stdlib-only constraint for plugin scripts.** Already documented in
  `docs/invariants.md:76`; no new entry needed.

### Bug observed (cross-wave): T-475 exit-on-unregister regression
Same survival pattern as wt-t430/t432/t435. Already filed.

### Quality gate
Passed on main after fast-forward.

## State after this wave

- `plugins/cloglog/scripts/set_yaml_keys.py` is the canonical scalar-YAML
  upsert helper for any other init/config step that needs it.
- `docs/design/templating-modernization.md` row #8 → done.
- Next-priority F-58 row: #31 (T-468, JSON POST body hand-rolling).
