# Work Log — wt-t309-search-mcp-instructions

## Task
T-309: Update plugin instructions to recommend `mcp__cloglog__search` for T-NNN/F-NN/E-N lookups.

## PR
https://github.com/sachinkundu/cloglog/pull/234 — squash-merged at 2026-04-26T16:16:16Z (merge commit 2b2a1bb).

## What changed
- `plugins/cloglog/skills/launch/SKILL.md`
  - Step 1b rewritten: `mcp__cloglog__search` is now the first move for resolving F-*/T-* references; `get_board` / `list_features` / `get_active_tasks` are fallbacks for genuine enumeration only. Explicit "never `psql` the board" line added.
  - Step 2 of the agent-template Workflow: `mcp__cloglog__search` added to the spawned-agent ToolSearch preload list, with a one-liner on the rationale.
- `tests/plugins/test_plugin_search_guidance.py` (new): pin test, two cases — Step 1b body must mention `mcp__cloglog__search`; at least one `select:...` token in the file must list `mcp__cloglog__search`. Asserts by **presence** so the next paraphrase that drops the recommendation fails CI.

## Codex review
- Round 1 (HIGH): flagged that I included `E-*` in `/cloglog launch` argument-parsing wording, but launch has no epic-launch path. Narrowed Step 1b back to F-*/T-* and added an explicit note that epics are containers with no launch semantics. Replied on PR; pin tests still pass (they assert search-presence, not E-*).
- Round 2: `:pass:`. Auto-merge gate returned `merge` (no human CHANGES_REQUESTED, both checks bucket=pass, no hold-merge label). Squash-merged via `gh pr merge --squash --delete-branch`.

## Quality gate
- `make quality` PASSED both before round-1 push and before round-2 push (913 backend tests, 54 invariants, MCP server, contract, demo auto-exempt). Coverage 88.40%.
- New pin test passes both pre- and post-round-1 narrowing (assertion is `mcp__cloglog__search` presence, which survived the E-* removal).

## Surfaces audited but not changed
The `grep -rnE "(get_board|get_active_tasks|get_backlog|list_features|list_epics)"` sweep showed surviving references in `init/SKILL.md` (project-existence check) and `reconcile/SKILL.md` (walks the full board to reconcile worktree state). Both are legitimate enumerations, not entity-by-number lookups, so they were left alone — per the task brief's exclusion of "hierarchy paging" use cases.
