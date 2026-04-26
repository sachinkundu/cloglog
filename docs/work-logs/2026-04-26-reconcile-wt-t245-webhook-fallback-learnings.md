# T-245 — learnings

## Don't silently break a documented deployment contract

The first patch replaced the `settings.main_agent_inbox_path` env var fallback
with a `worktrees.role` column lookup outright. Tests passed because the test
suite drove the new path; the regression hid behind unchanged docs. Codex
caught it: `.env.example` and `src/shared/config.py` still advertised the env
var, and the `/cloglog setup` step that registers the main agent is manual,
so an operator who set the var but hadn't yet run setup would see unmatched
PR events silently dropped.

Lesson: when replacing a documented runtime contract, either retire the
contract end-to-end (delete the setting, update `.env.example`, document the
upgrade) or chain the old path as a fallback. Don't leave the docs claiming
behavior that the code no longer provides. The chained-fallback option was
in-scope here; full retirement would have required edits outside the
worktree's scope (`src/shared/config.py`, `.env.example`).

Pattern for future reviewers: when a PR rewires resolution logic, grep
`.env.example` and `config.py` for any setting that fed the old path, and
verify the docs and the runtime still agree.

## Path-based role derivation needs a stable marker

The role is derived from the worktree path via the `/.claude/worktrees/`
segment marker (`_WORKTREE_PATH_MARKER` in `src/agent/services.py`). The
backfill SQL uses the same `LIKE '%/.claude/worktrees/%'` pattern. Both must
stay in sync — if the worktree directory layout ever moves, both the model
default-derivation logic AND the migration's backfill SQL would need updating.
The project's `Project.repo_url` does not store a local repo-root path, so
this convention is the only available signal without adding a new field.
