# Wave: reconcile-wt-t473-memento-research

**Date:** 2026-05-06
**Worktree:** wt-t473-memento-research
**PR:** [#335](https://github.com/sachinkundu/cloglog/pull/335) — `docs(T-473): memento evaluation memo (no-fit verdict)`
**Invoked from:** main agent salvage (skip_pr commit on wt branch → main agent pushed + PR'd as bot)

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t473-memento-research | cooperative + main-agent salvage | 2 | Agent set skip_pr=True and committed locally; main agent pushed + opened PR #335 so the doc would land. Codex round 1 flagged broken cross-link to plumb memo (sibling on different branch); fixed by softening the wording. Round 2 `:pass:`. |

## Commits

```
ad5f3f5 docs(T-473): soften plumb cross-link (codex finding — sibling memo not in this checkout)
55dbddd docs(T-473): memento evaluation memo
```

## Files changed

- `docs/research/memento-evaluation.md` (new — 112 lines, 8 sections)

## Per-task summary (from `work-log-T-473.md`)

**Verdict: no-fit.** Two load-bearing reasons:

1. Memento binds transcripts to commits — the wt-t475 mid-task crash today (no commit reached, nothing to bind) is the exact failure memento would need to close, and falls outside its model.
2. Per-project setup cost (binary install, workflow, provider config) contradicts F-59's "across all cloglog-managed projects" goal.

**Zero follow-ups filed.** All three candidates failed the self-defense rule.

Memento (process-of-work / transcript-as-audit) and Showboat/Rodney (proof-of-work / artifact verification) are orthogonal — a memento note cannot replace a Rodney screenshot on a frontend PR.

The memo preserves memento as a future option if F-59 ever becomes a *legally durable provenance* requirement (compliance, not engineering audit) — `git notes` is the cleanest off-the-shelf primitive in that scenario.

## Learnings & Issues

### Pattern: skip_pr docs tasks need a salvage step

T-473 (and T-472, T-479) all set `skip_pr=True` and committed locally. Without main-agent salvage, the commit would have been torn down with the worktree and the doc lost. The skip_pr workflow assumes the operator/main-agent does something with the commit before close-wave. **This is a real workflow gap** worth noting: skip_pr should either (a) push the branch at agent-side or (b) be reserved for tasks whose deliverable is purely board-state, never disk artifacts. Not filing a task today — operator deleted 35 follow-ups yesterday for less. If this pattern recurs across multiple research waves, file then.

### Codex round 1 finding (resolved round 2)

Cross-link to sibling plumb memo was broken because plumb memo lives on a different branch. Softened wording in two places (lines 11 and 112) to clarify the sibling memo is on PR #336 and not in this checkout. Codex round 2 `:pass:` confirmed.

### Quality gate
Passed on main after fast-forward.

## State after this wave

- `docs/research/memento-evaluation.md` is the canonical memento evaluation under F-59.
- Sibling T-472 plumb memo lands separately via PR #336.
- No follow-up tasks generated — the self-defense rule held.
