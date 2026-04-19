# Learnings — wt-fix-localhost

**Date:** 2026-04-19

## What went well

- **Self-contained demo.** The Node fetch reproduction spawns its own IPv4-only HTTP server, tests both loopback families, and tears down — no backend infra required for `showboat verify`. This matters because `scripts/check-demo.sh` runs `uvx showboat verify` with no servers up. Any demo block that talks to the project backend (`$BACKEND_PORT`, gunicorn on 8001, etc.) will record fine via `make demo` but fail on the `make demo-check` re-run. Future demos for infra-ish behaviors should follow the same self-contained pattern.
- **Scope guard held.** Three-file fix plus demo, nothing else. Tempting targets (`Makefile` echoes, Playwright helpers, plugin fallback URLs) were correctly left alone because the failure mode is specific to Node's fetch + IPv4-only bind, and those other contexts don't share it.
- **Codex reviewer caught a real latent bug.** The first cut used `DEMO_FILE="docs/demos/$(git rev-parse --abbrev-ref HEAD)/demo.md"` — works for `wt-fix-localhost` but would produce `docs/demos/feat/foo/demo.md` on slash-named branches, which `check-demo.sh` can't discover because it scans one directory level under `docs/demos/*/` and normalizes slashes to hyphens. Fix was to mirror the same `${BRANCH//\//-}` substitution in the demo-script template.

## Issues encountered

### `.venv` partially populated (pre-existing)
- `uv run pytest` inside this worktree fell through to pyenv's pytest shim because `.venv` only had `respx` installed but not `pytest`, `mypy`, `ruff`, `pytest-cov`, etc. `make quality` inherited the failure as "`ModuleNotFoundError: No module named 'respx'`" during collection — misleading because `uv run python -c "import respx"` succeeded.
- **Resolution:** `uv sync --extra dev` (NOT `--group dev`) pulls the full test/lint toolchain from `[project.optional-dependencies].dev`. The `[dependency-groups].dev` table carries a subset.
- **Fix candidate:** `.cloglog/on-worktree-create.sh` should run `uv sync --extra dev` after creating `.venv` so new worktrees have a complete toolchain on first `make quality`.

### `mcp-server/dist/` in prompt vs reality
- AGENT_PROMPT.md step 7 said "Commit the resulting `mcp-server/dist/` artifacts too (they are checked in; see existing PRs in git log)". Reality: `dist/` is listed in both the repo-root `.gitignore` and `mcp-server/.gitignore`. `git log -- mcp-server/dist/` returns nothing. I rebuilt dist locally (required for `make quality`'s contract check) but did not commit it — worktree bootstrap regenerates it.
- **Fix candidate:** the prompt template for devex tasks touching `mcp-server/src/` should say "rebuild dist locally (`cd mcp-server && make build`) so `make quality` has the current artifact, but do not commit — dist is gitignored."

### Hardcoded branch name in demo-script
- `demo-script.sh` template uses `$(git rev-parse --abbrev-ref HEAD)` raw in the `DEMO_FILE` path. Silent failure waiting to happen on any slash-named branch.
- **Fix candidate:** update `plugins/cloglog/skills/demo/SKILL.md`'s demo-script template to `BRANCH="$(git rev-parse --abbrev-ref HEAD)"; DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"`. This matches `scripts/check-demo.sh`'s existing `FEATURE_NORM="${FEATURE//\//-}"` convention.

### Stale `shutdown-artifacts/` from prior worktree
- The worktree inherited `shutdown-artifacts/work-log.md` and `learnings.md` skeletons from `wt-depgraph` (2026-04-05). Had to overwrite them. Same issue flagged in the F-11 learnings.
- **Fix candidate (unchanged from F-11):** launch script should either reset these files or delete them so each agent starts from a clean template. (Tracked as T-242 under F-48.)

## Suggestions for CLAUDE.md / plugin updates

- **CLAUDE.md — Environment Quirks:** add a bullet for `uv sync --extra dev` on new worktrees before running `make quality`, and note the `--extra dev` vs `--group dev` distinction. `[dependency-groups].dev` ≠ `[project.optional-dependencies].dev`.
- **`plugins/cloglog/skills/demo/SKILL.md`:** update the demo-script template snippets (both backend and frontend variants) to use `${BRANCH//\//-}` when composing `DEMO_FILE`. Lead-by-example; check-demo.sh already normalizes.
- **`plugins/cloglog/on-worktree-create.sh`:** add `uv sync --extra dev` after `.venv` creation, and reset `shutdown-artifacts/*.md` to empty stubs so prior-worktree content doesn't leak in.
- **Devex-task prompt template:** when a task touches `mcp-server/src/`, explicitly state that `dist/` is gitignored — avoid the "they are checked in" misstatement this prompt carried.
