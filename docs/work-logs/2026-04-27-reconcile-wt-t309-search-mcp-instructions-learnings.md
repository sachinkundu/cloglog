# Learnings — wt-t309-search-mcp-instructions

## Codex caught wording-vs-implementation drift

The task brief said "T-NNN/F-NN/E-N lookups" because `mcp__cloglog__search` accepts E-* (it does — search returns id/type/number for epics too). I parroted that into Step 1b's `/cloglog launch` argument-parsing wording without checking whether the launch *pipeline* knows what to do with an epic. It doesn't: Step 2 only prepares spec/plan/impl tasks for features, and the spawned-agent template only knows how to execute tasks. Documenting `E-*` as a valid argument would have let an operator type `/cloglog launch E-3`, get a UUID resolved, and then hit an undefined downstream path.

**Generalisable lesson:** when the task brief uses a list of entity types ("T-NNN/F-NN/E-N"), don't promote that list verbatim into the documented argument grammar of an *unrelated* surface. The set of entities a *resolver tool* accepts is not the same as the set of entities a *workflow command* knows how to act on. Audit each surface against its own downstream code paths before widening its accepted input.

## Pin tests by *presence* survive narrowing

The pin test asserts `mcp__cloglog__search` appears in Step 1b body and in a `select:...` token. When codex made me drop the `E-*` wording, the test continued to pass without modification — because it pins the *recommendation* (which is the load-bearing rule), not the *example list* (which is implementation detail). Counterpart: presence-pins don't catch over-broadening; absence-pins do. Use presence for "this guidance must remain"; use absence for "this antipattern must not return".

## `gh pr merge --delete-branch` from a worktree exits non-zero on success

Already in CLAUDE.md as a learning. Hit it again: the squash-merge succeeded server-side (`mergedAt` set, state MERGED), but the local cleanup (`git checkout main && git branch -D`) failed because the parent clone owns `main`. Verified with `gh pr view <num> --json state,mergedAt` per the playbook. Merge handler ran cleanly afterward.

## Auto-merge gate is the right ratchet

Once the second-round codex review came in with `:pass:`, the four-condition gate returned `merge` (no human CHANGES_REQUESTED, both checks pass, no hold-merge label) and the merge happened in one command. No human round-trip needed for a docs-only PR with a single round of codex feedback addressed. Worth preserving.
