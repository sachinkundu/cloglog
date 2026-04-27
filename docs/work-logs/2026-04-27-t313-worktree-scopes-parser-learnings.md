# Learnings — T-313 Phase 0b parser

These are durable gotchas observed during this task. Each one bit me (or
nearly bit me) on this PR; each one is worth folding into CLAUDE.md
under "Plugin hooks: YAML parsing" or an adjacent section.

## Absence-pins react to literal substrings — including in the safety comments that explain them

`tests/plugins/test_no_python_yaml_in_scalar_hooks.py` enforces
`"import yaml" not in body` for each hook. When I added a safety
comment in `protect-worktree-writes.sh` reading "The previous
`import yaml` snippet swallowed ImportError…", the absence-pin tripped
on my own explanatory text. The file passed `make quality` because the
quality output got truncated above the failing line, and only Codex
round 2 surfaced it.

**Lesson:** when authoring an absence-pin or a comment near one,
*never* mention the forbidden token in narrative form — paraphrase
("PyYAML-based snippet", "the previous python+PyYAML block"). And
**always grep `make quality` output for `FAIL`** instead of trusting
the green tail; the gate exits non-zero but the trailing PASSED line
in earlier output came from a stale invocation, not the current one.

## Fail-closed in safety hooks: the *parser* must error and the *caller* must propagate

The first cut of the new hook had `ALLOWED=$(parser …) || exit 0`
because that mirrored the original `... 2>/dev/null) || exit 0` shape.
That preserved exactly the silent allow-all bypass T-313 was meant to
eliminate. The original pattern was safe in context (the original
parser never errored — it `try/except`-ed everything to `[]`), but
copy-pasting the shape onto a *strict* parser inverts the safety
property.

**Lesson:** when retrofitting a permissive component to a strict one,
audit every `|| exit 0` / `|| true` / `2>/dev/null` on the calling
side — they were workarounds for the old component's noise floor and
become silent bypasses against the new one. The audit checklist is:
*for each error path the new component now signals, what does the
caller do with it?* If the answer isn't "block + log", the migration
isn't complete.

## `gh pr merge --delete-branch` from a worktree exits non-zero but merges server-side

Already documented in CLAUDE.md ("Skills that touch GitHub" / `gh pr
merge`). This bit me again — `gh pr merge --squash --delete-branch`
printed `failed to run git: fatal: 'main' is already used by worktree
at '/home/sachin/code/cloglog'` but the squash had already landed.
Verified with `gh pr view 239 --json state,mergedAt` per the existing
guidance. Worth re-reading that section before reacting to a non-zero
exit on `gh pr merge`.

## Auto-merge gate's `ci_not_green` re-trigger is synchronous, not webhook-driven

When Codex `:pass:`-es before CI terminates, the gate returns
`ci_not_green`. There is no inbox event for "CI turned green" — the
webhook consumer only emits `ci_failed`. The gate handler in the
github-bot skill explicitly `gh pr checks --watch`-s in-line and
re-evaluates once. Worked exactly as documented this run; worth
flagging that the synchronous wait can take 3+ minutes for a
single-commit CI run, which is fine but easy to mistake for a hang.
