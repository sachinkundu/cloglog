# Work Log — T-300 (Prod-branch tracking rollout)

**Worktree:** `/home/sachin/code/cloglog/.claude/worktrees/wt-t300-prod-branch-rollout`
**Branch:** `wt-t300-prod-branch-rollout`
**PR:** [#226](https://github.com/sachinkundu/cloglog/pull/226) — merged 2026-04-26 12:50 UTC at `cbfd157`
**Spec:** `docs/design/prod-branch-tracking.md`
**Task IDs:** T-300 (`516124be-e702-4a26-8fa5-646d023d7d94`) under F-50 (Worktree Close-off, `8fc781a3-88a1-4087-a7e4-1f15a18165da`)

## Scope

Bundled spec §10 tasks T-prod-2 / T-prod-3 / T-prod-4 / T-prod-5 / T-prod-6 / T-prod-9 into one PR. Branch surgery (T-prod-1) was completed by the operator before this agent started:

- `origin/prod` exists at the same SHA as `origin/main`.
- `cloglog-prod` worktree (`/home/sachin/code/cloglog-prod`) tracks `origin/prod`.
- The dev clone (`/home/sachin/code/cloglog`) sits on local `main`.

## What shipped (final state at merge SHA cbfd157)

- **`Makefile` `promote` target** rewritten: `git fetch origin && merge --ff-only origin/main` advances local `prod`, then deploy steps (uv sync, vite build, alembic upgrade, gunicorn HUP, frontend preview), then **finally** `git push origin prod`. The push is gated behind `set -e` over the deploy block so failures abort before publishing the new SHA, preserving the "origin/prod always reflects deployed code" invariant from spec §3.3.
- **`make verify-prod-protection`** new target. Uses operator's `gh` auth (the GitHub App PEM has no `administration` scope by design). Asserts:
  - `required_linear_history.enabled == true`
  - `required_pull_request_reviews == null` (PRs forbidden — `make promote` is a direct push)
  - `restrictions.users.length == 1` (single operator account)
  - `restrictions.apps.length == 0` (no app, no agent)
  - `restrictions.teams.length == 0`
  - Distinct exit codes: 0 = pass, 1 = policy violation, 2 = credential/auth issue.
- **`CLAUDE.md` Runtime & Deployment** documents prod tracks `prod`, plus a "Rollback path" subsection covering both pre-promote (revert PR on main) and post-promote (stop → reset prod worktree → restart → revert PR).
- **`docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md`** carries a "Superseded for branch-tracking by `docs/design/prod-branch-tracking.md` (T-292)" header.
- **`plugins/cloglog/skills/close-wave/SKILL.md`** and **`plugins/cloglog/skills/reconcile/SKILL.md`** retargeted from `git pull origin main` to `git fetch origin && git merge --ff-only origin/main` (spec §5.4), with explicit "investigate divergence, do not paper over" guidance. The bigger detached-HEAD push fold remains in T-301 / T-prod-7 scope.
- **Memory** `~/.claude/projects/-home-sachin-code-cloglog/memory/feedback_setup_park_on_main.md` rewritten from "fetch + detach to origin/main" recipe to "checkout main + ff" recipe; pending-task paragraph removed; `MEMORY.md` index entry updated to match.

## Codex review iterations

Codex challenged the PR three times before passing:

1. **Session 1/5** — `verify-prod-protection` was wired to `BOT_TOKEN`, but the App PEM lacks `administration:read`, so `gh api` returned 403 and the suppressed error misreported "linear history not enabled". Fixed in 7adf5da: drop the BOT_TOKEN coupling, let `gh` use the operator's auth, case-match the response (403 / 401 / 404 / other) with distinct exit codes.
2. **Session 2/5** — three findings in 85e987a:
   - `git push origin prod` ran before the deploy steps, so a failed `vite build` would publish a not-yet-deployed SHA. Moved push to end of recipe + `set -e`.
   - Restriction check counted `users + apps + teams` as one number, so an apps-only configuration would falsely pass. Tightened to assert `apps == 0`, `teams == 0`, `users >= 1` separately.
   - `close-wave/SKILL.md:264` and `reconcile/SKILL.md:296` still said `git pull origin main` even though CLAUDE.md now told operators dev sits on local `main` (a hazard introduced by this PR itself). Retargeted both lines.
3. **Session 3/5** — two findings in 4b3610a:
   - Verifier didn't check `required_pull_request_reviews`. An operator enabling "Require a pull request before merging" would break `make promote` silently while `verify-prod-protection` still printed OK. Added the assertion.
   - `users >= 1` allowed multiple humans, defeating the single-operator gate. Tightened to `users == 1`.
4. **Session 4/5** — `:pass:`. Auto-merge gate evaluated → `ci_not_green`, watched `gh pr checks` to terminal state, re-evaluated → `merge`, squash-merged.

## Operator-action note

Branch protection on `prod` is **not yet applied** in the GitHub UI. `make verify-prod-protection` will fail until the operator configures the rules per spec §3.2. Applying protection is a one-time UI step; the verifier confirms it post-rollout.

## T-prod-9 smoke-test plan (operator action, post-merge)

The actual smoke test runs on the operator's host because `make promote` mutates live prod. After this PR merged into `main` (it has), the operator runs:

```bash
cd /home/sachin/code/cloglog
make promote                                  # fast-forwards prod from origin/main, deploys, pushes origin/prod
git -C ../cloglog-prod rev-parse HEAD         # local prod SHA after deploy
git ls-remote origin refs/heads/prod          # remote prod SHA — must match local
curl -sI https://cloglog.voxdez.com | head -1 # service responding
```

Acceptance:
- `prod` SHA advances on `origin` (load-bearing because future Railway deploy will read this ref).
- `git ls-remote origin refs/heads/prod` matches the SHA gunicorn is running.
- `https://cloglog.voxdez.com` serves the new content.

If the operator wants to pre-flight without touching prod: `git -C ../cloglog-prod fetch origin && git -C ../cloglog-prod merge --ff-only --no-commit origin/main` is a no-op locally (since `prod` is currently at the same SHA as `main` plus this PR's merge commit). The actual rotation is what `make promote` does end-to-end.

## Follow-ups filed for the wave

- **T-301** (T-prod-7 + T-prod-8): retire the close-wave/reconcile detached-HEAD push codepath, replace with natural `wt-reconcile-*` branch + PR flow; add a pre-commit hook on the dev clone rejecting direct commits to `main`. Depends on this PR merging first (it has).
