# Work log — wt-t437-jinja2-renderer

Closed: 2026-05-05.
Wave name: t437-jinja2-renderer (single-task wave; ran in parallel with wt-t438).

## Worktrees

| Worktree | Branch | Tasks | PR | Shutdown path |
|----------|--------|-------|----|---------------|
| wt-t437-jinja2-renderer | wt-t437-jinja2-renderer | T-437 | [#325](https://github.com/sachinkundu/cloglog/pull/325) | cooperative + tab-close cleanup (T-428 recurrence #4) |

## What shipped (from `work-log-T-437.md`)

`plugins/cloglog/scripts/render_template.py` swapped its `str.replace` engine for **Jinja2** with `autoescape=False`, `StrictUndefined`, `keep_trailing_newline=True`. Placeholder syntax flipped from `@@KEY@@` (uppercase, regex `[A-Z_][A-Z0-9_]*`) to `{{ key }}` (lowercase Jinja2). Two templates, the launch SKILL's `--var` calls, and the design doc all moved in lockstep.

The metacharacter-safety contract from T-354 was preserved on the new engine — values containing `&`, `\`, `|`, `$`, or newlines round-trip verbatim (autoescape OFF, Jinja2 substitutes literally). Adversarial pin tests (`test_launch_sh_renders_clean`, `test_task_md_round_trips_metacharacters`) carry that assertion forward unchanged.

PR #325 merged 2026-05-05T07:23:52Z (merge `fd20266`). Codex 3 rounds — see codex review history below.

### Files touched

- `plugins/cloglog/scripts/render_template.py` — Jinja2 engine, AST walk via `find_undeclared_variables`, env-fallback tries lower-case key first then `key.upper()` (back-compat for `TASK_NUMBER` / `WORKTREE_PATH` exporters).
- `plugins/cloglog/templates/{task.md,launch.sh}.template` — `{{ key }}` syntax, lowercase names.
- `plugins/cloglog/skills/launch/SKILL.md` — `uv run --with jinja2` invocation pattern in Steps 3 + 4e.
- `plugins/cloglog/docs/launch-design.md` — refreshed engine description and editing rules.
- 4 pin-test files updated to `{{ key }}` and `uv run --with jinja2 ...` subprocess shape.
- New `test_uppercase_env_fallback_renders_lowercase_placeholder` (codex round 2 regression test).

### Codex review history

- **Round 1 (MEDIUM)** — `from jinja2 ...` import broke the `python3 render_template.py` launch contract. Switched every call site to `uv run --with jinja2 ...`. Removed brief `jinja2>=3.1.0` from `pyproject.toml` runtime deps so `uv run --with` is the single declared entrypoint, mirroring `gh-app-token.py`.
- **Round 2 (HIGH + 2× MEDIUM)** —
  - (a) env-fallback regression: lower-case-only env lookup broke callers that exported `TASK_NUMBER` / `WORKTREE_PATH`. Fixed by trying lower first, then `key.upper()`. Pinned by uppercase-env regression test.
  - (b) script docstring still showed `python3 render_template.py …` — replaced with the real `uv run --with jinja2` shape.
  - (c) `launch-design.md:76` still described the SKILL recipe as a single `python3` invocation — refreshed to wrapper shape with rationale.
- **Round 3 (`:pass:`)** — auto-merge gate accepted; squash-merged.

## Shutdown summary

- Cooperative path: `agent_unregistered` clean, per-task work log delivered.
- **T-428 recurrence #4 in this supervisor session.** Launcher 2169690 + claude underneath stayed alive after `unregister_agent`. Tab close (via `close-zellij-tab.sh`) terminated claude via SIGHUP; launcher's `wait` returned, no trap fire. The pattern is fully deterministic now — every cleanly-merging session in this supervisor exhibits the same hook-failure shape.

## Decisions worth highlighting

- **Engine: Jinja2.** Settled the recurring "build it ourselves vs. use the engine" pressure. Future templating sites (multi-line, conditionals, loops) are a `{{ var }}` away. `uv run --with jinja2` keeps the dep-declaration boundary at runtime — no `pyproject.toml` runtime entry, mirroring `gh-app-token.py`'s `uv run --with PyJWT[crypto]` pattern.
- **Lowercase placeholder names.** Matches Jinja convention; reads as natural Python code. Env fallback handles legacy uppercase export paths via `key.upper()` shim — load-bearing for the supervisor's pre-T-437 export pattern, see residual notes.
- **`StrictUndefined`.** Missing `--var` errors loud (preserves T-354's strict-by-default contract). `--allow-unset` opt-in path retained.

## State after this wave

- Templating engine settled on Jinja2. F-58 sweep (T-435) can proceed against an established pattern.
- T-438 (sibling, sonnet) still in review with PR #326 — independent surfaces (github-bot SKILL, gh-app-token.py, classifier allowlist, gitignore pin). Will close-wave separately when it merges.
- T-428 recurrence count: 4. **Should be expedited**; the deterministic pattern means every future close-wave in this session will need the same tab-close cleanup.
- F-58 templating sweep (T-435) gains the canonical engine choice it needed before it could file migration tasks.

## Residual notes

- The env-fallback `key.upper()` shim is intentional and load-bearing for the supervisor's pre-T-437 export pattern. Removing it without auditing every export site (close-wave, reconcile, init, launch SKILL Step 4e) will silently break agent renders.
