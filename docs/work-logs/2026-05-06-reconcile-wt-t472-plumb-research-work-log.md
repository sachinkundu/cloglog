# Wave: reconcile-wt-t472-plumb-research

**Date:** 2026-05-06
**Worktree:** wt-t472-plumb-research
**PR:** [#336](https://github.com/sachinkundu/cloglog/pull/336) — `docs(T-472): plumb evaluation memo (no-fit verdict)`
**Invoked from:** main agent salvage (skip_pr commit on wt branch → main agent pushed + PR'd as bot)

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t472-plumb-research | cooperative + main-agent salvage | 2 | Same skip_pr salvage pattern as T-473/T-479. Codex round 1: 1 HIGH + 1 MEDIUM (ddd-reviewer is repo-local, not shipped via plugin); fixed in round 2 `:pass:`. |

## Commits

```
5c6ea31 docs(T-472): clarify ddd-reviewer is repo-local not shipped via plugin (codex round 1)
c261fb9 docs(T-472): plumb evaluation memo — no-fit verdict
```

## Files changed

- `docs/research/plumb-evaluation.md` (new — 256 lines, 7 sections)

## Per-task summary

**Verdict: no-fit.** Five reasons in priority order:

1. Plugin-incompatible by construction — Python-only, can't live in a plugin shipped to Go/TS downstream repos.
2. Interactive `plumb init` ritual patches CLAUDE.md and installs hooks — incompatible with "plugin appears and just works" model.
3. Mandatory `ANTHROPIC_API_KEY` at commit time — credential-sprawl regression.
4. In-repo `.plumb/` state directory must be committed (high-conflict surface).
5. Per-commit LLM latency layered on `make quality`.

**Zero follow-ups filed.** One narrow idea preserved in the memo (annotation-based test↔requirement convention, e.g. `# inv:NN` for invariant pin tests) but explicitly NOT filed — no concrete delinking incident has occurred today, the self-defense rule rejects "nice-to-have annotation convention" filing.

Plumb (spec↔test↔code provenance) and Showboat/Rodney (proof-of-work artifact verification) operate at different layers — orthogonal, neither replaces the other.

## Learnings & Issues

### Codex round 1 findings (resolved round 2)

- **HIGH** — verdict rationale named `ddd-reviewer` as a covering protection, but ddd-reviewer is repo-local (`.claude/agents/`), NOT shipped via the plugin. Downstream repos rely on demo + invariants alone. Qualified the rationale to make this explicit.
- **MEDIUM** — cross-link path was `plugins/cloglog/agents/ddd-reviewer.md` (doesn't exist); corrected to `.claude/agents/ddd-reviewer.md` and noted that only `pr-postprocessor.md` and `worktree-agent.md` ship via the plugin.

The HIGH finding is itself a small invariant worth noting: **claims about plugin coverage must verify against `plugins/cloglog/agents/`, not the repo's own `.claude/agents/`**. Repo-local protections do not transfer to downstream consumers. Not adding to `docs/invariants.md` today (no automated pin available), but worth flagging for any future audit that evaluates plugin portability.

### Quality gate
Passed on main after fast-forward.

## State after this wave

- `docs/research/plumb-evaluation.md` is the canonical plumb evaluation under F-59.
- Sibling T-473 memento memo merged via PR #335 earlier this morning.
- F-59 now has both research memos in `docs/research/`. Operator decides whether the feature has surfaced anything actionable, or whether F-59 closes with both no-fit verdicts.
- No follow-up tasks generated — the self-defense rule held throughout.
