# T-254 Learnings

Extracted from the review cycle on PR #157 — items worth propagating to future agents via `CLAUDE.md` or future tasks.

## 1. Filesystem probes belong where the filesystem lives

The initial patch ran `git` on the backend to derive `branch_name` from a worktree path. Reviewer caught that `docs/ddd-context-map.md` explicitly documents a split-deployment topology: `cloglog` runs on the host, `cloglog-mcp` runs inside each agent-vm, and **worktree paths are VM-local**. Host-side filesystem probes silently return empty (path not visible) in production, so the "fix" would have done nothing while the migration would have actively flipped legitimate live worktrees to `offline`.

**Rule:** Before adding a filesystem operation on a path that lives inside an agent sandbox, check `docs/ddd-context-map.md` and ask "does this process have access to that path?" If the answer is no, move the probe to the process that does (the MCP server for worktree paths, a heartbeat-bearing agent call for live state, etc.). The backend should only manipulate data it receives over the wire.

## 2. Additive data migrations, not destructive ones

The initial migration flipped `status='offline'` whenever the host couldn't see a worktree path. Under the VM topology that would silently kill every live agent's webhook routing. The correct shape for a backfill migration is *additive only*:

- Populate what you can actually verify.
- Leave unreachable rows alone — they self-heal on the next legitimate update (in this case, the next MCP `register_agent`).
- Destructive cleanup (marking things offline, deleting ghost rows) belongs in a dedicated reconciliation tool with richer context (F-48's `/cloglog reconcile`), not a one-shot migration that runs on every deploy.

**Rule:** Migrations that touch data should be idempotent and additive. If you find yourself writing `UPDATE ... SET status = 'offline'` or `DELETE FROM` inside an Alembic `upgrade()`, stop and ask whether that belongs in a reconciliation path instead.

## 3. Defensive guard on reconnect: don't wipe populated columns with empty values

`upsert_worktree` used to unconditionally overwrite `existing.branch_name = branch_name`. That meant if the MCP probe had a transient failure (git not ready yet, detached HEAD mid-operation), reconnect would wipe a good value with `""`, re-opening the same data trap the fix closes. The guard: only overwrite when the new value is truthy.

**Rule:** Upsert paths that take partial data should treat empty-string/null from the caller as "preserve existing," not "set to empty." This protects against transient probe failures clobbering persistent state.

## 4. `git symbolic-ref --short HEAD` beats `git rev-parse --abbrev-ref HEAD`

Initial draft used `rev-parse --abbrev-ref HEAD` (per the task prompt's suggestion). Two concrete edge cases broke tests:

- **Pre-first-commit repos:** `rev-parse` fails with `fatal: ambiguous argument 'HEAD'`.
- **Detached HEAD:** `rev-parse --abbrev-ref HEAD` returns the literal string `"HEAD"`, forcing the caller to special-case it.

`symbolic-ref --short HEAD` handles both cleanly — it works on empty repos and exits non-zero on detached HEAD, so a single `try/except` covers every unresolvable case.

**Rule:** When probing for a branch name, prefer `symbolic-ref --short HEAD` over `rev-parse --abbrev-ref HEAD`.

## 5. `docs/demos/<branch>` must use `${BRANCH//\//-}` normalization

`scripts/check-demo.sh` normalizes slashes to hyphens when discovering the demo directory. Any `demo-script.sh` that passes `$BRANCH` raw to `DEMO_FILE=docs/demos/$BRANCH/demo.md` will write into `docs/demos/feat/foo/` while check-demo looks at `docs/demos/feat-foo/` and fail. The repo already documents this as a recurring bite — see `docs/work-logs/2026-04-19-t247-fix-localhost-*.md` and the fixed example at `docs/demos/wt-fix-localhost/demo-script.sh:6`.

**Rule:** Every `demo-script.sh` MUST use `${BRANCH//\//-}` when constructing `docs/demos/...` paths. Worth adding to `plugins/cloglog/skills/demo/SKILL.md` so new agents don't hit it.

## Suggestions for CLAUDE.md

Add a note under "Project-Specific Agent Instructions":

> **Host/VM split affects data access.** cloglog (backend) runs on the host; cloglog-mcp runs inside each agent-vm. Worktree paths are VM-local. Before writing any code that stats, reads, or shells out to a path stored on a Worktree row from inside the backend, remember that path is NOT visible to the backend process in production. Derive such values in cloglog-mcp (which has the filesystem) and send them over the wire; make the backend a pass-through. Data migrations in `src/alembic/versions/` must not flip row status based on host-side filesystem probes for the same reason.

And reinforce the existing demo note:

> **Demo script slash-normalization.** `scripts/check-demo.sh` normalizes branch names with `${FEATURE//\//-}`. Your `demo-script.sh` MUST mirror that — use `BRANCH_DIR="${BRANCH//\//-}"` when constructing `docs/demos/$BRANCH_DIR/`, or `make demo-check` will fail on slash-named branches.
