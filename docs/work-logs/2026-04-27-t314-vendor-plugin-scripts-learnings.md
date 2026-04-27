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

## `replace_all` on SKILL.md edits can break counter pins on the strings the SKILL.md references

When using Edit with `replace_all=True` across a SKILL.md, the failure mode is not "pin tests that name the SKILL.md filename" — it's pin tests that count occurrences of a *literal cited inside* the SKILL.md. The `test_auto_merge_skill_handles_silent_holds.py` pin asserted `body.count("${CLAUDE_PLUGIN_ROOT}/scripts/auto_merge_gate.py") >= 2` against `github-bot/SKILL.md`'s body; the test does not mention `github-bot` or `SKILL` anywhere, so a filename-based grep would have missed it. After `replace_all` changed both occurrences of an unrelated rename, the count went to 0 silently. **Right grep before `replace_all`:** (a) `body.count(` / `template.count(` / `\.count(` patterns in `tests/plugins/`, then check whether each counted literal lives in the file you're editing; (b) the literal you're renaming itself (e.g., `auto_merge_gate.py`) — search every pin test for it. Filename-based grep is the wrong heuristic.
