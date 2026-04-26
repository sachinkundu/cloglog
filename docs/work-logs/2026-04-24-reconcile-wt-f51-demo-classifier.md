# Work Log — F-51 Demo Classifier (Diff-Aware Demo Gate)

**Close date:** 2026-04-24
**Wave:** wt-f51-demo-classifier (single-agent, eight-PR sequence)
**Tasks closed:** T-289 — Implement diff-aware demo classifier end-to-end (F-51)

## Shutdown summary

| Worktree | PRs | Shutdown path | Commits | Notes |
|----------|-----|---------------|---------|-------|
| wt-f51-demo-classifier | #208–#214, #216 | cooperative (agent self-unregistered; close-wave task absent due to `.cloglog/on-worktree-create.sh` 404 at bootstrap — ran before `register_agent`) | ~30 across 8 PRs | Post-processing handled by main agent post-processor. |

## PRs shipped

| PR | Title | Shape |
|----|-------|-------|
| #208 | PR 1/6: widen `scripts/check-demo.sh` allowlist + land F-51 spec/plan + pin test | Spec + gate base |
| #209 | PR 2/6: add `demo-classifier` subagent | New subagent |
| #210 | PR 3/6: `exemption.md` acceptance path in `scripts/check-demo.sh` + diff-hash pin test | Gate path |
| #211 | PR 4/6: update `cloglog:demo` skill (Step 0 + Step 1 + exemption PR body variant) | Skill update |
| #212 | PR 5/6: update `demo-reviewer` subagent — Dimension D (exemption audit) + Dimension E (missing-screenshot guard) | Reviewer update |
| #213 | PR 6/6: add Demo expectations section to codex review prompt | Codex integration |
| #214 | PR 7: fix diff_hash self-invalidation (exclude `docs/demos/` from hashed diff) | Bug fix |
| #216 | Proof PR: live exit-condition demo — exercise classifier → exemption.md → gate → reviewers end-to-end | End-to-end proof |

All eight merged. Total invariants after the wave: 54 (was 28 — five added by F-51, plus one regression pin in PR #214).

## Feature delivered

The demo gate now has three acceptance paths:

1. **Static allowlist** — scripts-only, Makefile-only, plugin-only changes pass without a demo artifact.
2. **`demo.md` + showboat verify** — frontend/API changes need a demo with passing exec blocks.
3. **`exemption.md` + diff_hash** — internal changes can exempt themselves; classifier emits `no_demo` verdict with a locked hash; `scripts/check-demo.sh` re-computes the hash at gate time and rejects stale exemptions.

Components: `demo-classifier` subagent, updated `cloglog:demo` skill (Steps 0–1), updated `demo-reviewer` (Dimensions D+E), updated codex review prompt (Demo expectations section), and `scripts/check-demo.sh` gate. All six mechanically pinned by 54 invariants in `docs/invariants.md`.

## Exit condition verification

Per `AGENT_PROMPT.md` Step 10 (proof PR required):

- PR #216 landed via `exemption.md`. Classifier verdict `no_demo`, `exemption.md` committed, gate printed `Exemption verified (diff_hash matches)` on the committed HEAD, merged.
- `demo-reviewer` Dimension D fired on #216: verdict `valid exemption — approved`; full rubric traced.
- codex comment on #216 explicitly cross-checked `diff_hash` against the excluded diff, confirmed no runtime-visible change, returned `:pass:`. Demo expectations section active but correctly did NOT flag a valid exemption.
- `make invariants` → 54 passed. `make quality` → green.

## Codex review rounds (summary)

24 codex review turns across 8 PRs. Key corrections per PR:

- **#208** — widened regex to include nested `package-lock.json` and `plugins/*/{skills,agents,templates}/` (original allowlist broke rollout's own PRs). Passed round 2.
- **#209** — corrected HTTP route rule to span all DDD contexts (decorators, not filenames); corrected MCP tool paths to `server.ts`/`tools.ts`. Passed round 2.
- **#210** — passed round 1.
- **#211** — 5 rounds; found scope creep in worktree-agent/github-bot templates; hit codex 5-session cap; user merged.
- **#212** — 4 rounds; fixed DEMO_DIR exact-match, `fN-*` collapse, `@router.*` pattern, MERGE_BASE fallback, bootstrap shape. Passed round 5.
- **#213** — removed scripts/Makefile from CLI surfaces. Passed round 2.
- **#214** — 3 rounds; swept stale two-dot diff references; reverted two-dot to three-dot with inline commentary. Passed round 3.
- **#216** — passed round 1.

## Bug discovered during proof run

The six rollout PRs shipped green invariants, but the test suite's happy-path `exemption.md` fixture left the file untracked. Running the real agent flow (commit `exemption.md`, then gate) immediately exposed the self-invalidation bug: committing `exemption.md` changes the diff bytes, changing the SHA256, invalidating the stored `diff_hash`. Fixed in PR #214: all hash-computation sites use `git diff ... -- . ':(exclude)docs/demos/'`; new regression pin `test_exemption_commit_does_not_invalidate_its_own_hash` compares hash before/after commit.

## State after this wave

- All six F-51 components live in main.
- 54 pin tests covering every mechanical invariant in `docs/invariants.md`.
- `docs/demos/wt-f51-demo-classifier/exemption.md` committed — classifier's own output from the proof run.
- Known follow-up (out of F-51 scope): extract the static allowlist regex from its three copies (check-demo.sh, SKILL.md Step 0, classifier) to a single source file.
- Known gap: static-allowlist PRs (scripts-only, Makefile-only) have no `docs/demos/<branch>/` directory, so codex's Demo section cannot audit them. By design — documented explicitly in the codex review prompt with the rationale.

---

## Learnings (from shutdown-artifacts/learnings.md)

### Allowlist regexes must be validated against the actual repo path tree

The F-51 spec's initial allowlist omitted nested `package-lock.json` paths (`frontend/` and `mcp-server/`, not root) and narrowed `plugins/` to just `hooks/` — the rollout's own PRs 4/6 touched `plugins/cloglog/skills/` and would have failed their own gate. Grep the actual repo for every path class before writing an allowlist; a narrow-by-accident regex blocks the feature it enables.

### Route rules: key on decorator, not filename

The classifier and demo-reviewer initially targeted `src/gateway/**/routes.py`. This repo mounts routers from every bounded context plus `sse.py`, `webhook.py`, and `app.py`. MCP tools were similarly mis-pathed. Codex caught both in PR #209 round 1. When a rule says "user-observable HTTP routes," key on the decorator (`@[A-Za-z_]*router\.(get|post|patch|put|delete)\(`), not on the filename.

### Test fixtures that shortcut the production flow can hide the exact failure mode you care about

The exemption pin tests wrote `exemption.md` untracked (convenient, covers the happy path). The real agent flow commits the file, which changes the diff bytes. The self-invalidation bug was invisible to the test suite but caught immediately by the proof PR. Pin tests should reflect the production flow, not just the mechanical invariant.

### Two-dot vs three-dot git diff matters for diff_hash correctness

`git diff A B` (two-dot) vs `git diff A...B` (three-dot): when `A` is a resolved merge-base SHA both produce identical bytes; when `A` is a raw ref and main has advanced, two-dot includes main's new commits as "removed." Always use three-dot form in the classifier (safe for both caller shapes); use two-dot in check-demo.sh only after upstream resolution. Document the equivalence condition explicitly so future edits don't silently converge on the unsafe form.

### Codex's 5-session cap is a hard ceiling; bundle scope correctly in round 1

PR #211 hit the cap without approval. Each round found "also this other file" scope-creep findings that rippled outward. When a PR starts generating round-after-round of sibling-file findings, the change is still expanding scope. Bundle the correct scope into round 1.

### "One PR per task" is a heuristic; sequentially-dependent rollouts are a legitimate exception

The memory says one PR per task. F-51 is one task (T-289) with eight sequentially-dependent PRs on one branch, rebasing between merges. Worked fine. When a task's structure genuinely requires each step to merge independently for safety (no Big Bang), sequential PRs on one branch are the right shape.
