# Learnings — T-314 (wt-t314-vendor-plugin-scripts)

## `.env` files are NOT auto-sourced by Claude agents or shell launchers

When a plugin script needs env vars, the correct pattern is:
```bash
export GH_APP_ID=<id>
export GH_APP_INSTALLATION_ID=<id>
```
in `~/.bashrc` / `~/.zshenv`, or via direnv with a `.envrc`. A `.env` file in the project root is never sourced automatically — this silently breaks any agent that relies on it. Always use shell RC or direnv for vars that must survive into subprocess invocations.

## `uv run --with <pkg> python <script>` beats `sys.executable` in pytest subprocess tests

When a test subprocess needs packages not in the test venv (e.g. `requests`, `PyJWT`), use:
```python
["uv", "run", "--with", "PyJWT[crypto]", "--with", "requests", "python", str(script_path)]
```
`sys.executable` points to `.venv/bin/python3` which may lack those packages, causing `ModuleNotFoundError` under `--cov=src`.

## Absence-pin tests asserting a literal string work even when the string isn't in the file yet

Writing an absence pin for a string that doesn't currently appear is still correct practice — it guards against future regressions. The point is catching the antipattern if it ever comes back, not catching something today.

## `replace_all` on SKILL.md edits can break other pin tests

When using Edit with `replace_all=True` across a SKILL.md, check all existing pin tests that reference the same file before committing. The `test_auto_merge_skill_handles_silent_holds.py` test pinned `plugins/cloglog/scripts/auto_merge_gate.py` count ≥ 2; after replace_all changed both occurrences, the count was 0. Always grep pin tests for the file being edited.
