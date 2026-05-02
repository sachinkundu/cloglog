# Worktree wt-t363-bot-url-no-mutate — aggregate work log

Single-task worktree. PR #281 merged 2026-04-30.

---

---
task: T-363
title: Stop mutating origin URL with bot token — push via inline URL instead
feature: F-46 Agent Lifecycle Hardening
pr: https://github.com/sachinkundu/cloglog/pull/281
status: merged
worktree: wt-t363-bot-url-no-mutate
codex_rounds: 5
---

# T-363 — Inline-URL bot push (no `.git/config` mutation)

## Summary

Three SKILLs (`close-wave` Step 13, `reconcile` Step 5, `github-bot` Push +
Create) all ran `git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git"`
before `git push -u origin HEAD`. The mutation was permanent; after any
of those SKILLs ran, the operator's `origin` was authenticated as the
bot. `make promote` then pushed `prod` as the bot and `prod`'s ruleset
rejected the push — breaking the entire promote flow until the operator
manually reset `origin`. Tokens also expired in `.git/config` after ~1h,
and `git remote -v` leaked the credential.

Replaced with an inline-URL push that does not touch `.git/config`:

```bash
git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git" "HEAD:${BRANCH}"
git fetch origin "${BRANCH}"
git branch --set-upstream-to=origin/${BRANCH}
```

## Files touched

- `plugins/cloglog/skills/close-wave/SKILL.md` — Step 13 push
- `plugins/cloglog/skills/reconcile/SKILL.md` — Step 5 push
- `plugins/cloglog/skills/github-bot/SKILL.md` — Push + Create (replace recipe + new "Operator self-rescue" subsection)
- `CLAUDE.md` — "Branch protection / verification" + "Skills that touch GitHub" sections updated
- `docs/work-logs/2026-04-26-t301-close-wave-rewrite-learnings.md` — superseded older recipe with inline-URL form
- `tests/plugins/test_skills_no_remote_set_url.py` — new pin test (3 cases)
- `tests/plugins/test_init_smoke_ci_workflow.py` — added third assertion pinning init-smoke.yml inclusion
- `.github/workflows/init-smoke.yml` — wired new pin into every-PR gate
- `Makefile` — added test to `invariants` target
- `docs/invariants.md` — new "SKILLs that touch GitHub" section

## Codex round-by-round

1. **Round 1 (MEDIUM):** `CLAUDE.md` "Skills that touch GitHub" section still
   prescribed the retired recipe. Fix: updated CLAUDE.md + the older T-301
   work-log lesson with a supersede note.
2. **Round 2 (MEDIUM + HIGH):**
   - `git branch --set-upstream-to=origin/${BRANCH} 2>/dev/null || true`
     silently failed because raw-URL push doesn't update
     `refs/remotes/origin/${BRANCH}`. Verified locally: `@{u}` still
     resolved to `origin/main` after a fresh raw-URL push. Fix: insert
     `git fetch origin "${BRANCH}"` first; drop `|| true` so a real
     failure surfaces.
   - Self-rescue command hardcoded HTTPS, silently flipping SSH clones
     to HTTPS. First fix attempt: sed-strip the credential prefix only.
3. **Round 3 (HIGH):** the round-2 sed-strip claim "preserves whatever
   scheme the operator's clone uses" was false — once the bot URL has
   overwritten origin, the original scheme cannot be inferred. Fix:
   replace the single sed with two explicit operator-choice lines
   (HTTPS or SSH) and a sentence telling the operator to pick the
   form matching their original clone.
4. **Round 4 (MEDIUM):** new pin not wired to enforcement paths.
   `ci.yml`'s `paths:` filter excludes `plugins/**` and `CLAUDE.md`,
   so a SKILL-only future edit reintroducing the antipattern would
   ship green. Fix: wired to `init-smoke.yml` (every PR), `make
   invariants`, and `docs/invariants.md`.
5. **Round 5 (HIGH):** init-smoke.yml inclusion not pinned itself —
   `test_init_smoke_ci_workflow.py` only asserted the two older
   entries. Fix: added `test_workflow_runs_skills_no_remote_set_url_pin`
   alongside the existing pair.

## Self-dogfooding

Every push from round 2 onward used the new inline-URL recipe. After
round 2's push, verified `@{u}` resolved to
`origin/wt-t363-bot-url-no-mutate` (proving the fetch+set-upstream-to
fix was real, not just documented). After every push, `git remote
get-url origin` returned the canonical `https://github.com/sachinkundu/cloglog.git`
— no embedded token.

## Tests / quality

- `make invariants` — 61 tests (was 58); all pass.
- `make quality` — PASS at every commit.
- `tests/plugins/test_skills_no_remote_set_url.py` — 3 tests pass.
- `tests/plugins/test_init_smoke_ci_workflow.py` — 6 tests pass (was 5).

## Residual TODOs / context the next task should know

- The `t301-close-wave-rewrite-learnings.md` work-log was edited inline
  rather than left frozen because it is referenced as workflow guidance
  ("Lesson:" framing). If we later treat work-logs as immutable, this
  pattern should be reconsidered — but for now CLAUDE.md is the canonical
  "Skills that touch GitHub" reference and the work-log carries a
  supersede note pointing back to it.
- The new pin is **fence-scoped** (`bash` code fences only), per the
  CLAUDE.md "Absence-pins on antipattern substrings collide with
  documentation that names the antipattern" learning. Future absence pins
  on SKILL.md content should follow the same shape — match the
  executable form, not arbitrary prose.
- The 5/5 codex round count was reached; the PR was operator-driven
  for the merge. Each round surfaced a real, distinct issue, which
  is the expected pattern for a documentation/infra PR with multiple
  feedback surfaces (prose, recipes, enforcement wiring, pin coverage).
- `make promote` was not directly tested in this task — the fix is
  prophylactic. The next operator promote against `prod` will be the
  first end-to-end validation that the antipattern is gone for real.
