# Learnings — T-300 (Prod-branch tracking rollout)

Durable, non-obvious lessons surfaced by codex reviews and verification work on PR #226. Fold candidates for `CLAUDE.md` Agent Learnings.

## GitHub App PEM has no `administration` scope — branch-protection inspection is operator-run

`scripts/gh-app-token.py` mints installation tokens with `contents` / `pull_requests` / `issues` / `workflows` permissions only. `gh api repos/:owner/:repo/branches/<br>/protection` returns `403 Resource not accessible by integration` against any App-minted token, with `X-Accepted-Github-Permissions: administration=read`. Verification targets that need branch-protection state must use the operator's personal `gh auth` (e.g. `gh auth login --scopes 'repo,admin:org'`), not `BOT_TOKEN`. Suppressing the 403 with `2>/dev/null` is worse than surfacing it — the check then misreports the policy state. Surface the API response, case-match it, and use distinct exit codes for credential issues vs policy violations so callers can distinguish operator-setup problems from real policy gaps.

## Branch-protection assertions must be exhaustive, not "non-empty list"

A protection rule that allows only the GitHub App, or only a team, or two human users, can all defeat the operator-only promotion gate while a naive non-empty-count check still prints OK. Spec §3.2 of `docs/design/prod-branch-tracking.md` defines the contract — *and the verifier must mirror every clause of it*, not just the most obvious one:

- `required_linear_history.enabled == true` (no merge commits on prod)
- `required_pull_request_reviews == null` (PR requirement would break `make promote`'s direct push)
- `restrictions.apps == []` (no app, no agent)
- `restrictions.teams == []`
- `restrictions.users.length == 1` (single operator — multiple humans defeat the single-gate guarantee)

Each clause is a separate assertion with a specific failure message naming the offending principal. "Number of users + apps + teams" rolled up to one count loses every interesting failure mode.

## `make promote` step ordering: the side-effect that publishes "deployed" must come last

`origin/prod` is the canonical "what is live" pointer (spec §3.3). Pushing it before `uv sync` / `vite build` / `alembic upgrade` / worker rotation creates a window where `origin/prod` advanced but the running service is still on the previous SHA — a silent lie any deploy tooling reading the ref will believe. Move the publish-the-pointer step (`git push origin prod`) to after the deploy block, gate the deploy block with `set -e`, and only then advance the remote ref. Generalises to any "ground truth from a remote ref" pattern — the ref is a contract; only update it after the contract holds.

## Retargeting `git pull` to ff-only is load-bearing once a worktree has a writable local branch

Plain `git pull origin <branch>` happily creates a merge commit when the local branch has diverged. Skills that ran `git pull origin main` were safe while the dev worktree couldn't check out `main` (it sat on detached HEAD); the moment the dev worktree was given a writable local `main`, every one of those `git pull` lines became a hazard. Spec §5.4 of `docs/design/prod-branch-tracking.md` flagged the exact lines (`close-wave/SKILL.md:264`, `reconcile/SKILL.md:296`); retargeting them to `git fetch origin && git merge --ff-only origin/main` and surfacing divergence as an investigation prompt (not a paper-over) closes the safety hole.

When you change *who* checks out a branch, audit every `git pull` against that branch before shipping the worktree-arrangement change.

## Codex's 5-session cap rewards catching the full review surface in round 1

This PR took 4 codex sessions because the first three submissions each had legitimate findings that should have been caught locally:

1. Calling a real API verifies the 403 (not just "the command exists").
2. Spec §3.2 is one sentence with five clauses — assert each clause, not the union.
3. Step ordering matters when the side-effect is the source-of-truth pointer.

A `make verify-prod-protection` smoke run + a careful re-read of spec §3.2 / §5.1 / §5.4 before the first push would have collapsed sessions 1-3 into zero. Apply this on any future "implement the spec" task: clause-by-clause checklist against the spec, then run the new commands, then push.
