# Learnings — T-301 (close-wave/reconcile branch+PR rewrite + dev-clone main-commit guard)

Each entry is a non-obvious gotcha that caused a real failure (or a near-failure caught by codex). Following the CLAUDE.md "Agent Learnings" pattern — only durable, grep-able insights.

## Editing skill snippets — always include the bot-authenticated form

**Symptom:** Codex PR #230 round 1 flagged 2 MEDIUM findings: both close-wave Step 13 and reconcile Step 5 showed bare `gh pr create --base main --head wt-...` snippets. An operator following them literally would open the PR under their personal `gh auth` and break the bot-identity invariant the github-bot skill exists to enforce (`plugins/cloglog/skills/github-bot/SKILL.md:34,58-63`).

**Lesson:** when a skill teaches a workflow that touches GitHub, every example command must be bot-authenticated end-to-end (`BOT_TOKEN=$(...)`, `git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git" "HEAD:${BRANCH}"`, `git branch --set-upstream-to=origin/${BRANCH} 2>/dev/null || true`, `GH_TOKEN="$BOT_TOKEN" gh ...`). Saying "use the github-bot skill's flow" in prose is not enough — readers copy the command they see, not the prose around it. Pin tests should assert the bot-authenticated form is present (positive substring), not just the unauthenticated form is absent.

> **Note (T-363):** the original recipe in this lesson used `git remote set-url origin "https://x-access-token:..."` followed by `git push -u origin HEAD`. That mutated `.git/config` persistently and broke `make promote` (`prod`'s ruleset rejects bot pushes). Superseded by the inline-URL push form above; `CLAUDE.md` "Skills that touch GitHub" is the canonical reference.

## Pin tests — the leak-after-fix rule applies even to retired patterns that were *never* literal strings

**Symptom:** the patterns the spec told me to pin out (`git checkout --detach origin/main`, `git push origin HEAD:refs/heads/wt-close-`) were not literal strings in the current SKILL files — earlier edits had already paraphrased them away.

**Lesson:** still pin them. The bug looked correct in tests because the workaround "worked" — the cost was integration-flow rot, not a unit-test failure. Absence asserts are the only way to catch a future revert. Pinning a string that doesn't currently appear is not redundant — it's the entire point.

## `gh pr merge --delete-branch` from a worktree errors but still merges

**Symptom:** ran `gh pr merge 230 --squash --delete-branch` from a worktree where `main` is checked out by the parent clone. The squash merge succeeded server-side, but the local post-merge cleanup (`git checkout main && git branch -D <branch>`) failed with `fatal: 'main' is already used by worktree at '/home/sachin/code/cloglog'` and the command exited 1.

**Lesson:** the merge itself is server-side and idempotent — confirmed via the `pr_merged` webhook event arriving on schedule. The local-side cleanup is what fails from a worktree. Don't panic if `gh pr merge` exits non-zero — verify with the inbox event or `gh pr view <num> --json state,mergedAt`. If you need clean post-merge state on the worktree, do the ff-and-prune from the main clone (`make` target or a separate skill step), not as a side-effect of `gh pr merge`.
