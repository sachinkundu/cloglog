# Learnings — wt-codex-sandbox (T-249)

**Date:** 2026-04-19

## What went well

- **The prompt named the exact file + line range + before/after snippet.** Turned a 5-minute edit into a literal patch application. A well-specified standalone task does not need a spec/plan pipeline.
- **Regression test as a "tidy up" guard.** Asserting the *absence* of `--sandbox`, `--full-auto`, and `danger-full-access` (not just the presence of the bypass flag) is what future-proofs this. Positive-only assertions let a cleanup pass silently re-add the bad flags alongside the good one.
- **Live evidence beats synthetic demos.** Evidence #1 in the demo is the actual `:warning: bwrap: loopback` text from the cloglog-codex-reviewer bot's review on PR #152. That ships stronger conviction than any contrived repro.
- **End-to-end verification fell out for free.** The merged PR's own codex review came back `:pass:` listing 10 files read outside the diff — that IS the end-to-end proof the fix works; no separate integration test needed.

## Issues encountered

### `--sandbox danger-full-access` is misleadingly named
- Despite "full access" in the name, it still invokes bwrap for network-unshare. The codex CLI's sandbox modes are all bwrap-wrapped; the only way to skip bwrap is `--dangerously-bypass-approvals-and-sandbox`.
- The 2026-04-18 fix (cb466bb) was a reasonable guess from the mode name but turned out wrong. Second-time-in-a-row on this host.
- **Fix-forward hygiene:** the in-code comment added in this PR explicitly warns future passes off reinstating `--sandbox`. Any cleanup pass that doesn't read comments earns the same failure.

### Worktree venv had no dev extras installed
- `uv run pytest tests/gateway/test_review_engine.py` failed collection with `ModuleNotFoundError: No module named 'respx'`. `pyproject.toml` lists `respx>=0.22.0` under dev/test extras; the venv had only runtime deps.
- Had to run `uv sync --extra dev` before tests would collect. Pre-existing across any freshly-created worktree that doesn't use its venv until the first `make quality`.
- **Fix candidate:** `.cloglog/on-worktree-create.sh` should run `uv sync --extra dev` after creating the venv, so tests are runnable on a fresh worktree without an extra step.

### Shutdown-artifact templates still stale
- `shutdown-artifacts/work-log.md` and `learnings.md` arrived carrying "wt-depgraph 2026-04-05" headers — the same issue flagged in the 2026-04-19 wt-task-deps learnings. Still not fixed.
- **Same fix candidate as before:** the launch script should either seed empty templates or delete the stale ones so the agent writes fresh files.

### Worktree branched behind origin/main
- Branch was 3 commits behind `origin/main` at start of work (T-247 merged in the interim). Also carried a stale `.mcp.json` edit in the working tree that had already landed upstream via PR #153.
- Handled by discarding the unstaged change and running `git merge --ff-only origin/main`. Harmless here because there were no local commits, but on a busy wave this is a rebase-vs-merge gotcha.
- **Fix candidate:** when creating a worktree, `on-worktree-create.sh` should branch from `origin/main` (not local main) AND discard any working-tree edits that are ancestors of origin/main, so agents don't inherit ghost state.

### Showboat `verify` compares outputs byte-for-byte
- First pass of the demo captured raw `pytest` output (`64 passed in 50.00s`) and raw codex session output (`tokens used 18,552`). Verify failed on the 50.00s→134.13s timing and 18552→18553 token drift.
- Fix: pipe through `grep -oE "[0-9]+ passed"` for pytest; for codex, assert booleans (`grep -q "^OK$"`) and emit stable `echo` lines instead of forwarding the raw stream.
- **Rule of thumb for demos:** if an `exec` block's output isn't deterministic, reduce it to a stable literal before capture. Don't stream raw tool output into showboat.

## Suggestions for CLAUDE.md / plugin updates

- **Worktree creation:** `uv sync --extra dev` after venv creation; discard any worktree edits already in `origin/main`; branch from `origin/main` (already a rule, restating because this worktree came in behind).
- **Shutdown artifacts:** clear the templates at launch time so agents can't inherit stale content from earlier worktrees.
- **Demo authoring note for CLAUDE.md:** add a one-liner under "Proof-of-Work Demos" — *"Showboat verify is byte-exact; any timing/token-count output must be filtered to a deterministic summary line before `showboat exec` captures it."* That saves the next agent one failed `make demo` cycle.
- **Codex argv:** keep the bypass flag. Any `--sandbox` mode on this host will dump core in bwrap's unshare-net until the kernel grants `CAP_NET_ADMIN`, which is not happening on a dev laptop. The in-code comment in `review_engine.py` now documents this — reference it before "tidying up" the flags.
