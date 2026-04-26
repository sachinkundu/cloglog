# Design Spec — `cloglog-prod` tracks a `prod` branch

**Task:** T-292 (under F-50 Worktree Close-off)
**Status:** Proposed
**Author:** wt-t292-prod-branch-spec
**Date:** 2026-04-26

## 1. Problem statement

The production worktree at `/home/sachin/code/cloglog-prod` is checked out on `main`. Because a branch can only be checked out in one worktree at a time, the dev worktree at `/home/sachin/code/cloglog` *cannot* sit on `main`:

```
$ git -C /home/sachin/code/cloglog-prod branch
* main
$ git -C /home/sachin/code/cloglog checkout main
fatal: 'main' is already checked out at '/home/sachin/code/cloglog-prod'
```

Three concrete consequences:

1. **Stale `wt-*` branches linger on the dev clone between sessions.** After a wave merges, the dev worktree's HEAD stays on the last merged `wt-*` branch (already gone on origin) instead of advancing to `main`. `git status` then shows phantom diffs against `main` and `make quality` runs against an arbitrary base. Documented in work log `docs/work-logs/2026-04-23-reconcile-wt-codex-review-badge.md:71` (`detached at 01d93ef and origin/main at 2bad450`).
2. **New worktrees inherit a wrong base ref unless explicitly told otherwise.** Memory `feedback_worktree_from_origin_main.md` exists *only* because of this — every worktree creation must say `origin/main` instead of the natural `HEAD`/`main`. One slip and unpushed local-main commits leak into the next PR (the original incident behind that memory).
3. **Every `/clear` and `/cloglog setup` runs a workaround.** Memory `feedback_setup_park_on_main.md` (current ground truth) instructs the main agent to `git checkout --detach origin/main` instead of `git checkout main`, because the natural form fails. Detached HEAD is acceptable for the dev worktree's idle state, but it is friction every session, and it forces `git checkout -b <wt-name> <sha>` semantics for any in-place commit work (see §7 / T-282).

The proposed fix removes all three consequences with a one-line conceptual change: **production tracks `prod`, not `main`.**

## 2. Proposal summary

`cloglog-prod` checks out a new long-lived branch `prod`, initially pointing at the current `origin/main` HEAD. `main` is freed and the dev worktree checks it out. A new `make promote` target fast-forwards `prod` to `origin/main` and triggers the existing zero-downtime worker rotation. The current `make promote` target (which already exists and pulls `origin/main` into `cloglog-prod`'s `main` branch) is reworked to operate on `prod`.

## 3. Branch model

### 3.1 Initial state

- Create branch `prod` on `origin` from current `origin/main` HEAD: `git push origin origin/main:refs/heads/prod`.
- In the prod worktree: `git -C ../cloglog-prod fetch origin && git -C ../cloglog-prod checkout prod && git -C ../cloglog-prod branch --set-upstream-to=origin/prod prod`.
- In the dev worktree (after the prod worktree releases `main`): `git checkout main && git pull --ff-only origin main`.

### 3.2 Push & protection

- `prod` is pushed *only* by `make promote` (running locally, as the user). No agent ever pushes to `prod`. PRs target `main`, never `prod`.
- Recommend GitHub branch protection on `prod`:
  - Require linear history (no merge commits — `prod` only fast-forwards from `main`).
  - Restrict pushes to the user's account (no app, no agent).
  - Do **not** require PRs — `make promote` is a fast-forward, not a PR target.
- `main` keeps its existing protection (PR + CI required). No change to `main`'s ruleset.

### 3.3 Relationship to existing concepts

- **`main`** — integration branch. Every PR merges here. CI runs on PRs targeting `main`. This is the "merged but not yet promoted" state.
- **`prod`** — what the live cloudflared-tunnelled service serves. Always equal to or behind `main`. Advances only via `make promote`.
- **The "Railway Deployment — Staging & Production" Epic** (referenced in `docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md:187` as F-35; not currently a board epic — see §9). When that epic lands, Railway will deploy from `prod` (or whatever branch is configured), and the local `cloglog-prod` worktree concept retires. *This spec is forward-compatible*: a `prod` branch is the natural Railway deploy source. Adopting `prod` now means F-35 only has to point Railway at `refs/heads/prod` — no further branch reshuffling.
- There is no separate `staging` branch in this design. If a staging environment is wanted, F-35 introduces it; `prod` is sufficient for the local single-prod-deploy world.

## 4. Promotion semantics

**Recommendation: keep promotion as a separate `make promote` step.** Do *not* fold the `origin/main → prod` fast-forward into `make prod`.

### 4.1 The two operations

| Operation | What it does today | What it does after this spec |
|---|---|---|
| `make prod` | Starts gunicorn + vite preview from `../cloglog-prod` (foreground). Asserts no other prod process owns `:8001`. | Unchanged — boots/serves whatever is currently checked out on `prod`. No git operations. |
| `make promote` | `git -C ../cloglog-prod pull origin main`, then `uv sync`, `npm ci`, `vite build`, `alembic upgrade head`, `kill -HUP gunicorn`, restart preview. | `git -C ../cloglog-prod fetch origin && git -C ../cloglog-prod merge --ff-only origin/main` (the prod branch is now `prod`, but it advances by ff-merging `origin/main`), then everything else as today. |

### 4.2 Why separate

- **Restartability without redeploy.** If the prod machine reboots or the gunicorn process dies, `make prod` should bring the service back on the *currently deployed* code. Folding promotion into boot would silently advance `prod` on every restart, defeating the gate.
- **Promotion is a deliberate user act.** The whole point of putting `main ≠ prod` is that "merged" and "deployed" are two states. `make promote` should remain the one human-driven moment.
- **Smaller blast radius for boot bugs.** A bad migration on `main` should not auto-apply on a service restart. With a separate `make promote`, an operator can `prod-stop && prod` to roll back to the deployed worker generation while investigating, without `make prod` re-running migrations.

### 4.3 Edge cases

- **Non-fast-forward `prod` advance.** Should not happen — `main` only ever has linear history relative to `prod` because `prod` is *only* advanced from `main`. If it ever does (someone force-pushed `main`), `git merge --ff-only` aborts and surfaces the conflict to the operator. Do not silently `--rebase` or `pull -X theirs`.
- **`prod` ahead of `main`.** Cannot happen if §3.2 protection holds. Hotfix story is in §8.

## 5. Audit — what hard-codes `main`

For each, **STAY** = no change needed; **UPDATE** = change required; **CONSIDER** = judgment call documented inline.

### 5.1 Makefile

- `Makefile:235-253` (`promote` target). **UPDATE** — change `git -C ../cloglog-prod pull origin main` to `git -C ../cloglog-prod fetch origin && git -C ../cloglog-prod merge --ff-only origin/main`. The downstream `uv sync`, `vite build`, `alembic upgrade head`, `kill -HUP` steps are unchanged.
- `Makefile:156-195` (`prod` target). **STAY** — boots from `../cloglog-prod`, no branch reference in the body.
- `Makefile:197-233` (`prod-bg`). **STAY** — same reason as `prod`.
- `Makefile:1` `.PHONY` line. **STAY** — `promote` already declared.
- All other targets (`dev`, `db-*`, `test*`, `lint`, etc.). **STAY** — branch-agnostic.

### 5.2 Scripts

- `scripts/preflight.sh`. **STAY** — does not reference `main` or any branch (verified by full read in research). Concerned only with binaries, daemons, the cloudflared tunnel, frontend `node_modules`, and the GitHub App PEM.
- `scripts/check-demo.sh:18`, `:28`. **STAY** — uses `origin/main` as the *PR base* for diff classification. PRs continue to target `main`, so origin/main remains the correct base. The local `main` fallback (`:29`) becomes more useful, not less, because dev now has a real local `main`.
- `scripts/run-demo.sh`. **STAY** — branch-agnostic.
- `scripts/test-demo-scripts.sh:90,93`. **STAY** — these test the "skip on main branch" branch of `check-demo.sh`. That logic is still correct (a branch *named* `main` does not need a demo).
- `scripts/sync_mcp_dist.py:17` (comment about `git pull origin main`). **STAY** — comment is about the close-wave pull, see §5.4.

### 5.3 Cloudflared tunnel & systemd

- The tunnel is systemd-managed (`scripts/preflight.sh` only checks the process). It points at `localhost:8001` (the prod gunicorn). It has no branch awareness. **STAY**.
- `CLAUDE.md:67` notes this. **STAY** unless §5.5 update is made.

### 5.4 Plugin skills (`plugins/cloglog/skills/`)

- `launch/SKILL.md:154-158`. **STAY** — instructs `git fetch origin main` and `git worktree add -b <wt> <path> origin/main`. Continues to be correct: worktrees branch off `main` (the integration branch), not `prod`.
- `close-wave/SKILL.md:108`, `:223`. **STAY** — `git log/diff main..<branch>` correctly compares feature branches against integration. (After this spec, `git log main..<branch>` resolves to local `main` which the dev worktree now has — *more* reliable than before.)
- `close-wave/SKILL.md:263-264` (`git checkout main && git pull origin main`). **STAY conceptually, becomes simpler**. Today this is impossible in the dev worktree (because of the issue this spec fixes); after the spec, this is the natural and correct close-out step. The `git checkout main` line becomes operational instead of aspirational.
- `close-wave/SKILL.md:298,322` (commit fixes to `main`). **STAY** — the commit target is `main`, which is now the dev worktree's actual branch. See §7 for the simplification.
- `reconcile/SKILL.md:296-297` (`git pull origin main` at end). **STAY** — same reason. Becomes naturally executable.
- `reconcile/SKILL.md:98` (stale-branch detection compares against merged-into-main state). **STAY** — `main` remains the merge target.
- `demo/SKILL.md:38, 62-69, 85`. **STAY** — uses `origin/main` as PR base (as in `scripts/check-demo.sh`).
- `github-bot/SKILL.md:46` (`git checkout main -- <file>`). **STAY** — the literal command is now executable in the dev worktree.
- `init/SKILL.md:201` (`git push -u origin main`). **STAY** — first-time bootstrap of a fresh project, unrelated to this spec.

### 5.5 Plugin hooks (`plugins/cloglog/hooks/`)

- `agent-shutdown.sh:93,98,139` (`git log/diff main..HEAD`, `git log --pretty %s%n%b main..HEAD`). **STAY** — same pattern. Local `main` is now the right base in worktrees because they branched off `origin/main`.
- `session-bootstrap.sh:4` (comment "main worktree"). **STAY** — the comment is about the *git worktree* concept, not the `main` branch.
- `worktree-create.sh:61` (`"branch": "${BRANCH}"`). **STAY** — not branch-content aware.
- `prefer-mcp.sh`, `protect-worktree-writes.sh`, `quality-gate`. **STAY** — not branch aware.

### 5.6 Configs

- `.cloglog/config.yaml`. **STAY** — `prod_worktree_path: ../cloglog-prod` is a path, not a branch. No branch keyed there.
- `.mcp.json`. **STAY** — branch-agnostic.
- `pyproject.toml`, `alembic.ini`, `docker-compose.yml`. **STAY**.
- Frontend env (`frontend/.env*`). **STAY** — only `VITE_API_URL` lives here.
- Backend `.env`. **STAY** — db URL, secrets, no branch ref.

### 5.7 CI / GitHub configs

- `.github/workflows/ci.yml:5` — `pull_request: branches: [main]`. **STAY** — PRs target `main`, that's correct. CI deliberately does *not* run on pushes to `prod` (the `main` → `prod` advance is a fast-forward of already-CI'd commits, no new code).
- **CONSIDER**: add a `push: branches: [prod]` smoke job that runs `make quality`? Recommend **no** — `prod` only ever holds commits that already passed CI on `main`; a second run is duplicate spend. Document this explicitly so the next person doesn't add it reflexively.

### 5.8 Docs

- `CLAUDE.md:61-67` (Runtime & Deployment). **UPDATE** — add one paragraph: "The prod worktree at `/home/sachin/code/cloglog-prod` tracks the `prod` branch (not `main`). `make promote` fast-forwards `prod` from `origin/main` and rotates workers. The dev worktree (this checkout) sits on `main`."
- `CLAUDE.md:92` (fast-forward learning). **STAY** — still correct; `git merge --ff-only origin/main` continues to be the right move before diff-based tools.
- `docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md`. **STAY (historical)** — that spec records the F-48 design as it shipped. Do not retroactively edit; this new spec supersedes it for branch-tracking semantics. Add a one-line forward reference at the top of the old spec: "Superseded for branch-tracking by `docs/design/prod-branch-tracking.md` (T-292)."
- `docs/work-logs/*`. **STAY** — historical record.

### 5.9 Memories

- `feedback_setup_park_on_main.md` (`~/.claude/projects/.../memory/`). **UPDATE** post-rollout — replace the detached-HEAD instructions with `git checkout main && git merge --ff-only origin/main`. The "why" line becomes shorter (the original constraint is gone). Memory itself flags this is pending (last paragraph).
- `feedback_worktree_from_origin_main.md`. **STAY** — still correct guidance. Its motivation (avoid leaking unpushed local-main commits into a worktree) survives this change; if anything it becomes more important because dev now genuinely commits on local `main` (close-wave fold commits, see §7), so the gap between local `main` and `origin/main` becomes a real surface.

## 6. Migration plan

Ordered, with verification after each step. Run as the user (not as an agent) — this is one-time infra surgery that touches branches.

1. **Create the `prod` branch on origin from current `origin/main`.**
   ```bash
   cd /home/sachin/code/cloglog
   git fetch origin
   git push origin origin/main:refs/heads/prod
   ```
   *Verify:* `git ls-remote origin refs/heads/prod` returns the same SHA as `git ls-remote origin refs/heads/main`.

2. **Switch the prod worktree to `prod`.**
   ```bash
   git -C /home/sachin/code/cloglog-prod fetch origin
   git -C /home/sachin/code/cloglog-prod checkout -b prod --track origin/prod
   ```
   *Verify:*
   ```bash
   git -C /home/sachin/code/cloglog-prod rev-parse --abbrev-ref HEAD     # → prod
   git -C /home/sachin/code/cloglog-prod rev-parse --abbrev-ref @{u}     # → origin/prod
   ```
   No restart needed — gunicorn re-reads source on `kill -HUP`, and the on-disk SHA hasn't changed yet.

3. **Free `main` on the dev clone and check it out.**
   ```bash
   cd /home/sachin/code/cloglog
   git checkout main && git pull --ff-only origin main
   ```
   *Verify:* `git rev-parse --abbrev-ref HEAD` → `main`; `git status` clean.

4. **Update `Makefile`** per §5.1 (`promote` body to use `fetch origin && merge --ff-only origin/main`).
   *Verify:* `make promote` performs a no-op fast-forward (because `prod` already equals `main`) and the rest of the steps still execute.

5. **Update `CLAUDE.md`** per §5.8.
   *Verify:* `make quality` still passes (markdown only, but the demo classifier sees a docs-only diff).

6. **Add the supersession header to `docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md`** per §5.8. One line at the top.

7. **Update memory `feedback_setup_park_on_main.md`** per §5.9. Replace detached-HEAD recipe with `checkout main + ff`. Drop the closing "pending task" paragraph.

8. **Apply branch protection on `prod`** in GitHub settings per §3.2.
   *Verify:* an attempted `git push origin :prod` (delete) and `git push --force origin abc123:prod` from the bot identity both fail with protection-rule errors.

9. **Smoke-test promotion.**
   - Land an inert PR on `main` (e.g., a one-line CHANGELOG entry).
   - Run `make promote`.
   - Confirm: `prod` SHA advances; gunicorn workers rotate (`/proc/<pid>/cmdline` shows new uvicorn workers); `https://cloglog.voxdez.com` serves new content.

10. **Close out:** any new lingering memories or CLAUDE.md mentions of "detached HEAD" / "main is checked out elsewhere" get scrubbed. (Boy-Scout, in a follow-on housekeeping task — not in the impl PR.)

## 7. Interaction with T-282

T-282 (#282 — "close-wave / reconcile: main agent commits without spawning a worktree (no wt-* prefix, detached-HEAD push)") exists *because* the dev worktree could not check out `main`. Its workaround is: when the main agent needs to commit a fold/reconcile/learnings update, it does so on detached HEAD and pushes via `git push origin HEAD:main` with the bot identity.

Once this spec lands, the dev worktree is on `main`. Fold/reconcile commits become natural:

```bash
# After this spec
cd /home/sachin/code/cloglog
git checkout -b wt-reconcile-<date>-<topic>      # short-lived
# ... edits ...
git commit -am "chore(reconcile): ..."
gh pr create --base main --head wt-reconcile-...  # via github-bot skill
# merge, then back on main:
git checkout main && git pull --ff-only origin main
git branch -D wt-reconcile-<date>-<topic>
```

This is the *exact same* workflow every other agent uses. No detached-HEAD push.

**Recommendation: close T-282 as obsoleted by T-292's impl tasks.** Fold the close-wave / reconcile updates into the §6 migration's final clean-up: when removing the detached-HEAD codepath, also remove T-282's guidance from the close-wave/reconcile skills. Filing them as separate impl tasks would be churn — they share a single edit.

If T-292 ships and T-282's underlying constraint persists for some unforeseen reason, T-282 can be reopened. Closing it pre-emptively is the right default given the tight coupling.

## 8. Rollback story

The prod-vs-main split exists *for* this scenario. If a bad commit lands on `main` and we don't want it on `prod`:

1. **Don't run `make promote`.** That's the entire gate.
2. Land a revert PR on `main`.
3. After the revert merges, `make promote` advances `prod` past both the bad commit and its revert.

If the bad commit is *already* on `prod` (operator ran `make promote` before noticing):

1. Stop the prod service: `make prod-stop`.
2. Roll the prod worktree back: `git -C ../cloglog-prod reset --hard <last-known-good-sha>`. Force-pushing to origin/prod is acceptable here because §3.2 restricts pushes to the user; if branch protection blocks the operator the recovery requires a temporary protection waiver. **Do not** try to revert via PR on `prod` — `prod` is fast-forward-only by design.
3. `make prod` to restart.
4. Land a revert PR on `main` so the next `make promote` doesn't re-pull the bad commit.

Document this in `CLAUDE.md`'s Runtime & Deployment section as the "rollback path" subsection (impl task).

## 9. Risks & open questions

1. **Branch-protection rules are a manual GitHub UI step.** Not enforced by code. If the operator forgets §6 step 8, agents (or anyone with bot push permissions) can push directly to `prod`. *Mitigation:* add a `make verify-prod-protection` script that calls `gh api repos/:owner/:repo/branches/prod/protection` and asserts the rules. Include in the impl plan.
2. **Railway deployment epic (F-35) is not on the board as an active epic** (verified via `mcp__cloglog__list_epics`). The reference in the original task description (`Epic "Railway Deployment — Staging & Production"`) is to the *spec* `docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md`, not a tracked epic. If F-35 is silently scheduled for the near term, this spec needs review against whatever Railway-specific branch model emerges. *Resolution:* file a follow-up to confirm with the user before impl starts whether F-35 is dormant or imminent.
3. **`alembic upgrade head` runs in `make promote`, not in `make prod`.** Today this is correct (CI ran it on `main`). Confirm no impl task accidentally moves `alembic upgrade head` into `make prod`'s startup; that would silently apply migrations on a restart-only-no-promote, which is exactly the "no auto-deploy on boot" guarantee §4.2 protects.
4. **Bot agents that have `git checkout main -- <path>` in their playbooks** (e.g., `github-bot/SKILL.md:46`) currently fail silently in the dev worktree because of the lock. After this spec they succeed — meaning the *behaviour changes* even if the docs don't. Pin test recommended: §4 of the impl plan should add a regression test that verifies `git checkout main -- <some-file>` in the dev worktree exits 0.
5. **Local `main` drift on the dev worktree.** Once dev has a real local `main`, agents could accidentally commit to it (e.g., a stray `git commit` not on a `wt-*` branch). The existing `protect-worktree-writes` hook protects worktree paths but not branch identity. *Mitigation:* a pre-commit hook on the dev clone that rejects commits on `main` unless `ALLOW_MAIN_COMMIT=1` is set (impl task; only a dev-clone setup chore, not part of the plugin).
6. **Cloudflared tunnel restart on prod-worktree branch switch.** Step 6/2 (`git checkout -b prod --track origin/prod`) doesn't change file content (since `prod` HEAD == `main` HEAD initially), so gunicorn doesn't need a restart. But `prod_worktree_path`-aware tools (e.g., the F-48 backend that resolves source-root from `Settings`) should be sanity-checked to ensure they care about the *path*, not the *branch name*. Read `T-255` learnings (`docs/work-logs/2026-04-19-t255-review-source-root-learnings.md`) before impl — that's the file with the most context.
7. **What if the user wants two prod environments?** (e.g., prod and a staging on a `staging` branch.) Out of scope for T-292; F-35 is the right place to design it. Note in the impl plan so it isn't accidentally pre-built.

## 10. Proposed follow-on impl tasks

Listed for the user to file on the board. Not created here.

| Task | Scope (one line) |
|---|---|
| T-prod-1 | Create `prod` branch on origin (one-time push) and switch the cloglog-prod worktree to track it. (Manual; user-run; verification commands provided.) |
| T-prod-2 | Update `Makefile`'s `promote` target to `fetch + merge --ff-only origin/main` instead of `pull origin main`. |
| T-prod-3 | Apply GitHub branch protection on `prod` (linear history, restricted push) and add `make verify-prod-protection` that asserts the rules via `gh api`. |
| T-prod-4 | Update `CLAUDE.md` Runtime & Deployment section: document `prod` branch, promotion semantics, and the rollback subsection from §8. |
| T-prod-5 | Header-supersede `docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md` with a one-line forward reference to this spec. |
| T-prod-6 | Update memory `feedback_setup_park_on_main.md` from "detached HEAD" to "checkout main + ff" recipe, and drop the pending-task paragraph. |
| T-prod-7 | Remove the close-wave/reconcile detached-HEAD push codepath (T-282 fold). Replace with the natural short-lived `wt-reconcile-*` branch + PR flow. Close T-282 in the same PR. |
| T-prod-8 | Add a pre-commit hook on the dev clone rejecting direct commits to `main` unless `ALLOW_MAIN_COMMIT=1` is set. (Dev-clone setup; do not put in the plugin.) |
| T-prod-9 | Smoke-test promotion end-to-end (inert PR → `make promote` → tunnel verification) and record the result in a work log. Final acceptance step. |

T-prod-1 is sequential and gates everything; T-prod-2 and T-prod-3 can be parallel after that; T-prod-4 / T-prod-5 / T-prod-6 are independent docs/memory edits; T-prod-7 depends on T-prod-1 (so the natural flow is reachable); T-prod-8 is independent; T-prod-9 is last.
