# Learnings: wt-main-inbox (T-253)

**Date:** 2026-04-20
**PR:** https://github.com/sachinkundu/cloglog/pull/164
**Task:** T-253 — main agent must receive webhook events for its own close-wave PRs

## What Went Well

- The opt-in via `Settings.main_agent_inbox_path` followed the T-255 precedent exactly — env var, `.env.example` documentation, `None` default preserves pre-change behavior.
- The `ResolvedRecipient` dataclass was the right call over a sentinel UUID. Self-documenting: `worktree_id=None` reads at the call site as "this is the main-agent fallback." Cost: a small dispatch-layer change so `handle()` reads from `recipient.inbox_path`.
- Codex caught a real correctness bug on the second review: my refactor collapsed the `project is None → return None` short-circuit into the `event.head_branch` branch, so any signed webhook for an unregistered repo could fall through to the main-agent fallback. Fix was a one-line hoist plus a regression test.

## Issues Encountered

- **Edit targeted wrong file on first pass.** I used `file_path: /home/sachin/code/cloglog/.env.example` (main repo root) instead of the worktree path. Git status in the main repo flagged it. Reverted with `git checkout .env.example` in the main repo, re-applied in the worktree. Worth a habit: every `file_path` must include `.claude/worktrees/wt-<name>/` unless I am explicitly in the main repo.
- **Showboat `exec` quoting footgun.** `bash -c 'command'` passed as argv gets interpreted in a way that strips the command; T-255's pattern is `bash 'command'` (no `-c`). Six `bash -c` invocations had to be rewritten. Demo skill already warns about the argv gotcha, but the specific `bash -c` vs `bash` distinction isn't obvious from the skill text.
- **AsyncMock against the resolver doesn't work.** `_resolve_agent` instantiates `BoardRepository(session)` internally, so mocking the `AsyncSession` returns `AsyncMock` coroutines where real SQLAlchemy rows are expected, and the first `.worktree_id` access explodes. Lesson: integration tests against this resolver need the real `db_session` fixture; demo proofs should grep or run pytest, not try to fake the resolver's internals.
- **Refactoring a short-circuit requires auditing every condition it protected.** I moved `find_project_by_repo` inside `if event.head_branch` so the branch-fallback could use it, but that decision also gated the foreign-repo guard on `head_branch`. For `ISSUE_COMMENT` (empty head_branch) the guard was dead — no real-world exploit today, but a latent leak once multi-project lands.

## Suggestions for CLAUDE.md

- Add to the "Cross-Context Integration" section: **when refactoring a webhook resolver that previously returned `None` at multiple gates, lift the gate conditions to a flat list at the top and re-verify every `None` return is still reachable from foreign / malformed input.** The diff can *look* equivalent while silently widening a surface.
- Add to the "Proof-of-Work Demos" section: **showboat `exec` takes `bash 'command'`, not `bash -c 'command'`** — follow `docs/demos/wt-reviewer-source-root/demo-script.sh` as the canonical template. The skill's argv note is easy to miss on first read.
- Add to "Worktree Discipline": **Edit and Write file_paths must include `.claude/worktrees/<wt>/`** — the hook only catches writes *inside* the worktree, not writes to the main repo's shadow copy of the same relative path.
