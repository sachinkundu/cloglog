# Work log — T-313 Phase 0b: nested worktree_scopes parser without global PyYAML

- **Branch:** `wt-t313-worktree-scopes-parser`
- **PR:** [#239](https://github.com/sachinkundu/cloglog/pull/239) — merged at 2026-04-27T07:42:40Z
- **Feature:** F-53 (plugin portability)
- **Worktree path:** `/home/sachin/code/cloglog/.claude/worktrees/wt-t313-worktree-scopes-parser`

## Outcome

Closed the last `python3 -c 'import yaml'` site in cloglog's plugin hooks. The
nested-mapping site at `plugins/cloglog/hooks/protect-worktree-writes.sh:52-72`
now goes through a vendored stdlib-only Python mini-parser at
`plugins/cloglog/hooks/lib/parse-worktree-scopes.py`. T-312 (PR #237) already
shipped the shared scalar-key shell helper for the four scalar sites; this PR
finishes Phase 0b of F-53.

The parser supports both flow-style (`board: [a, b]`, the production shape in
`.cloglog/config.yaml`) and block-style nested lists, rejects any other YAML
construct loudly with a line-numbered `parse error`, and preserves the
exact-match-then-longest-prefix scope lookup the original snippet did.

The hook now does the path-prefix check in pure bash and **fails closed** on
any parser non-zero exit *once a config file is found* (parse error, usage
error). Missing config remains fail-open — `find_config` returns non-zero
and `plugins/cloglog/hooks/protect-worktree-writes.sh:52` early-exits before
the parser runs; closing that path is filed as a follow-up to F-53
(see PR-review feedback on PR #240). The first cut also had
`ALLOWED=$(parser …) || exit 0`, which preserved the silent allow-all bypass
T-313 was meant to remove for the config-found path — Codex round 1 flagged
that as a real safety regression, and round 2 caught the literal
`import yaml` token I inadvertently put back into a safety comment.

## Commits

1. `1ee29e0` — fix(plugins): stdlib-only worktree_scopes parser (T-313)
2. `2034b39` — fix(plugins): protect-worktree-writes fails closed on parser error
3. `86216ef` — fix(plugins): drop literal yaml-token in hook comment to satisfy pin

## Files

- **New:** `plugins/cloglog/hooks/lib/parse-worktree-scopes.py` (~150 lines, executable, stdlib-only)
- **Modified:** `plugins/cloglog/hooks/protect-worktree-writes.sh` (-65 / +44; replaces both inline python+PyYAML blocks; adds `HOOK_DIR` resolution, fail-closed parser invocation, pure-bash prefix check)
- **New:** `tests/plugins/test_parse_worktree_scopes.py` (18 cases — parser shape, hook integration, stripped-env subprocess, malformed-config fail-closed pin)
- **Modified:** `tests/plugins/test_no_python_yaml_in_scalar_hooks.py` (docstring updated for T-312 + T-313; added absence + presence pins for `protect-worktree-writes.sh`)

## Reviews

- Codex session 1/5: caught `|| exit 0` fallthrough preserving the silent-bypass — fixed in 2034b39.
- Codex session 2/5: caught the literal `import yaml` substring I put back in a safety comment — fixed in 86216ef by rewording to "PyYAML-based snippet".
- Codex session 3/5: `:pass:`. Auto-merge gate held briefly on `ci_not_green` (CI was running on the just-pushed reword), then re-evaluated to `merge` after `gh pr checks --watch`.

## Verification

- `make quality` — green at 86216ef (956 passed, 1 xfail, coverage 88.45%, contract compliant, demo auto-exempt, MCP server build+tests pass).
- New parser smoke-tested against the live `.cloglog/config.yaml`: returns `src/board/,tests/board/,src/alembic/` for `board`, falls through prefix-match for `frontend-auth`.
- Hook integration test creates a real `git worktree`, asserts in-scope writes pass and out-of-scope writes block under `env -i PYTHONPATH=/dev/null`.
