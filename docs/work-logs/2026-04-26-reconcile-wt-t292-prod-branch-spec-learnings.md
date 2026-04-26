# Learnings: wt-t292-prod-branch-spec

**Date:** 2026-04-26

## What Went Well

- Aggressive `grep -rn` over plugin skills + hooks + scripts before drafting the §5 audit caught every concrete `main` / `cloglog-prod` reference. The codex reviewer found *no* missing files in the audit — only logic errors in the analysis.
- Two-step `git fetch + merge --ff-only` pattern (rather than `git pull`) was already the right CLAUDE.md learning (`CLAUDE.md:92`); the spec just needed to apply it consistently.

## Issues Encountered

- The original task brief contained a stale identifier (`T-282 (#282)`) that pointed at neither a real GitHub issue nor an open board task. Re-verifying the underlying *workflow* (close-wave/reconcile main-agent commits) against current `plugins/cloglog/skills/close-wave/SKILL.md` and `reconcile/SKILL.md` was the right move — referencing the workflow's actual location was more durable than chasing the ID. Lesson: when a brief cites a task ID, verify it (`gh api .../issues/N`, `mcp__cloglog__get_my_tasks` history, or work-log grep) before building a section around it.
- One reviewer finding turned on an empirically false claim: I asserted that `git checkout main -- <path>` fails in the dev worktree because `main` is locked. Codex tested it and proved otherwise (`git checkout <branch> -- <pathspec>` is path-scoped, doesn't change HEAD, doesn't interact with the worktree lock). Lesson: when claiming a "behaviour change" risk, run the command on the actual repo state first. One `bash` call would have caught the error before the spec went up.

## Suggestions for CLAUDE.md

Candidate addition under "Agent Learnings → Worktrees":

> **`git checkout <branch> -- <path>` is path-scoped and ignores worktree locks.** A locked branch (checked out in another worktree) blocks `git checkout <branch>` (HEAD-changing) but not `git checkout <branch> -- <path>` (file-restoring). When reasoning about worktree-lock consequences, only HEAD-changing checkouts and pulls are affected; pathspec-scoped operations work as normal.

Optional. The fact only matters when reasoning about the F-50 prod-branch reshuffle, so it may belong in `docs/invariants.md` as a `## Worktree lock semantics` note rather than CLAUDE.md.

Candidate addition under "Agent Learnings" (more broadly applicable):

> **Verify task IDs before building sections around them.** Briefs that cite `T-NNN (#NNN)` may carry stale identifiers — task IDs get reused for close-off work, GitHub issue numbers may not exist. Run `mcp__cloglog__get_my_tasks` (current) and `gh api repos/.../issues/N` (GitHub) to confirm both exist and refer to the work being described. If they don't, anchor the spec on the *workflow* (file:line citations) rather than the ID.

This one is more durable — applies to every spec, not just T-292's. Recommend including.
