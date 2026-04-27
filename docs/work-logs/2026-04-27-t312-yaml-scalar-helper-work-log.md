# Work Log — T-312 Phase 0a: shared YAML scalar-key helper across plugin hooks

**Worktree:** `wt-t312-yaml-scalar-helper`
**Branch:** `wt-t312-yaml-scalar-helper`
**PR:** https://github.com/sachinkundu/cloglog/pull/237 (MERGED 2026-04-27T07:07:16Z, squash 8fc0fd0)
**Task:** T-312 (Feature F-53)

## Summary

Replaced `python3 -c 'import yaml'` at 4 scalar-key sites with a stdlib-only sourced helper. Closed the silent-failure mode where the system python3 plugin hooks run under (typically without PyYAML) returned defaults instead of the configured value, producing wrong-port backend calls and broken parsing on portable hosts.

## Files

### Added
- `plugins/cloglog/hooks/lib/parse-yaml-scalar.sh` — `read_yaml_scalar <config> <key> [default]`. Top-level scalars only; strips quotes and trailing comments; honours default fallback for missing keys/files.
- `tests/plugins/test_parse_yaml_scalar_helper.py` — 10 unit tests including a stripped-env subprocess pin proving the helper is python-independent.
- `tests/plugins/test_no_python_yaml_in_scalar_hooks.py` — 5 absence + presence + cross-cut pins.

### Modified
- `plugins/cloglog/hooks/worktree-create.sh` — now sources helper, reads `backend_url` and `project`.
- `plugins/cloglog/hooks/quality-gate.sh` — now sources helper, reads `quality_command`.
- `plugins/cloglog/hooks/enforce-task-transitions.sh` — now sources helper, reads `backend_url` and `project_id`.
- `plugins/cloglog/skills/launch/SKILL.md` — `_backend_url()` in the launch.sh template uses inlined grep+sed (mirrors helper). Inlined rather than sourced because launch.sh runs as a standalone bash exec inside the worktree with no `CLAUDE_PLUGIN_ROOT` in scope.
- `tests/plugins/test_launch_skill_uses_abs_paths.py` — extended with a `_backend_url()` shape assertion.

### NOT touched (Phase 0b / T-313)
- `plugins/cloglog/hooks/protect-worktree-writes.sh` — reads the nested `worktree_scopes` mapping; the scalar-only helper cannot represent it. Phase 0b will ship a separate parser.

## Tests

`make quality` — PASSED (936 passed, 1 xfailed; demo gate auto-exempted as docs-only branch).

`uv run pytest tests/plugins/` — 44 passed including 19 new T-312 cases.

## Review

Codex (`cloglog-codex-reviewer[bot]`) approved with `:pass:` on session 1/5; CI (`ci`, `e2e-browser`) passed; auto-merge gate matched all 5 conditions and merged via squash.

## Notes

- Comments in the helper and hooks were re-worded from the literal `import yaml` substring to "the python YAML lib" so the absence-pin can sit beside warning comments without conflict.
- The launch.sh template render was syntax-verified by piping the heredoc through bash and running `bash -n` on the rendered file plus a `_backend_url` smoke call.
