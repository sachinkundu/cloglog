# Work log — wt-t438-t354-residuals

Closed: 2026-05-05.
Wave name: t438-t354-residuals (single-task wave; ran in parallel with wt-t437).

## Worktrees

| Worktree | Branch | Tasks | PR | Shutdown path |
|----------|--------|-------|----|---------------|
| wt-t438-t354-residuals | wt-t438-t354-residuals | T-438 | [#326](https://github.com/sachinkundu/cloglog/pull/326) | cooperative + tab-close cleanup (T-428 recurrence #5) |

## What shipped (from `work-log-T-438.md`)

Four independent fixes bundled in one PR (#326), each with its own pin test:

### Fix 1 — github-bot SKILL: guard `--delete-branch` in worktree context
Both `gh pr merge` call sites in `plugins/cloglog/skills/github-bot/SKILL.md` now detect worktree context via `git rev-parse --git-dir | grep -qF "worktrees"` and set `WORKTREE_MERGE_FLAGS=""` when inside a worktree. Pin: `tests/plugins/test_github_bot_skill_worktree_merge.py`. Closes the `'main' is already used by worktree at …` collision that bit T-354's PR push.

### Fix 2 — `gh-app-token.py`: bounded ancestor walk for `local.yaml`
New `_find_local_yaml(start)` checks the worktree root first, then walks up only until the first ancestor with `.cloglog/config.yaml` (the main checkout) — and **stops there**. Does NOT walk past the first config.yaml ancestor — prevents picking credentials from an unrelated parent directory. Codex round 3 strengthened the assertion to also pin the boundary check. Pin: `test_gh_app_token_script_walks_ancestors_for_local_yaml`.

### Fix 3 — demo allowlist: add `docs|scripts` + `README.md`
`demo_allowlist_paths` updated in `.cloglog/config.yaml`, `plugins/cloglog/skills/init/SKILL.md`, and `README.md` to:
- expand `^plugins/[^/]+/(hooks|skills|agents|templates)/` → `^plugins/[^/]+/(hooks|skills|agents|templates|docs|scripts)/`
- add `^README\.md$` (codex rounds 1–2 found README and init SKILL must stay in sync; this also auto-exempts README-only PRs)

Pin: `tests/test_check_demo_allowlist.py`.

### Fix 4 — `task.md` gitignore pin
New `tests/plugins/test_task_md_gitignore.py` runs `git check-ignore` against the real repo to verify the bare `task.md` rule applies at any depth and `plugins/cloglog/templates/task.md.template` is not blocked. New invariant entry in `docs/invariants.md`.

PR #326 merged 2026-05-05; codex 3 review rounds (init-SKILL allowlist sync, README sync, `_find_local_yaml` boundary tightening) → `:pass:` → auto-merge. Test delta +11 (1463 → 1474 passed).

## Shutdown summary

T-428 recurrence #5: launcher 2183498 + claude underneath stayed alive after `unregister_agent`; tab close cleared them. Same shape as recurrences #1-4 in this session. **The pattern is fully deterministic — every cleanly-merging session in this supervisor needs the same tab-close cleanup.**

## Decisions worth highlighting

- **Bounded `_find_local_yaml` walk.** First-config.yaml-ancestor stop is the correct boundary: it pins credentials to the same project the worktree belongs to, prevents inheritance from an unrelated parent directory, and doesn't require the agent to know which checkout is "main."
- **README.md added to allowlist.** Codex pointed out that adding `docs|scripts` to plugin subdirs would still trip the classifier on README-only PRs. Adding `^README\.md$` is a small net-positive — README docs PRs auto-exempt going forward.
- **`WORKTREE_MERGE_FLAGS` duplication is intentional for now.** The pattern lives at two `gh pr merge` call sites in the SKILL. Extracting to a shared helper is a clean refactor but not load-bearing — flagged in residuals for a future SKILL hygiene pass.

## State after this wave

- All four T-354 residual TODOs cleared. T-354's "Residual TODOs / context the next task should know" section is now closed (work logs reference T-438's PR).
- Demo classifier allowlist now matches both the cloglog repo's plugin layout AND the README documentation — bootstrap consistency.
- `gh-app-token.py` resolves `local.yaml` correctly from worktrees. Future close-waves should not see the `Error: GH_APP_ID is required` flake.
- T-428 recurrence count this session: 5. **Critical path.** Should be next-up.

## Residual notes

- `WORKTREE_MERGE_FLAGS` lives at two sites in github-bot SKILL — third call site needs the same guard. Future SKILL hygiene refactor (under F-56 audit) should extract.
- `_find_local_yaml` returns None when no main checkout has `.cloglog/config.yaml` (fresh project not yet inited). Falls back to worktree-root config.yaml — same as before. Acceptable.
- README.md allowlist only auto-exempts README-only PRs. Mixed README + source PRs still need a demo/exemption — README addition only helps pure-README work.
