# Work Log — wt-fix-localhost (T-247)

**Date:** 2026-04-19
**Worktree:** wt-fix-localhost
**Agent tasks:** 1 (landed in `review` with PR merged; administrative move to `done` is the user's.)

## Task shipped

| # | Task | Type | PR | Status |
|---|------|------|----|--------|
| 1 | T-247 — Fix committed localhost URLs — `.mcp.json` and `CLOGLOG_URL` default | task (standalone) | #153 | review (pr_merged=true) |

Standalone devex task, no pipeline — spec/plan skipped per prompt. One codex-review revision round (demo-script slash normalization), then pass.

## The fix

Three committed files defaulted to `http://localhost:8001`; every `git worktree add` copied them verbatim and the MCP server failed on the first tool call until a human patched `.mcp.json`. Root cause was IPv4-only server bind (`0.0.0.0`) vs Node fetch Happy Eyeballs preferring AAAA on Linux hosts where `localhost` resolves to `::1` first.

Changed to `http://127.0.0.1:8001` in:

- `.mcp.json:7` — `CLOGLOG_URL` env value
- `.cloglog/config.yaml:3` — `backend_url` (read by plugin hooks)
- `mcp-server/src/index.ts:12` — env fallback

`mcp-server/dist/` is gitignored (confirmed via `git log -- mcp-server/dist/`), so the rebuild was done locally for `make quality` but not committed. Worktree bootstrap regenerates it.

## PR

**#153** — `fix(devex): T-247 use 127.0.0.1 in committed MCP config (no more per-worktree patch)`. Two commits:

1. `1f6cea4` — the three-file fix + demo (`docs/demos/wt-fix-localhost/{demo-script.sh,demo.md}`).
2. `49d2af9` — review revision: normalize branch-slash → hyphen in the demo-script's `DEMO_FILE` path, matching `scripts/check-demo.sh`'s existing convention so slash-named branches can't break `make demo-check`.

Codex returned `:pass:` on round 2 after cross-reading `mcp-server/src/{index,client,server}.ts` and `.mcp.json`, `.cloglog/config.yaml`.

## Quality gates

`make quality` green on every push before merge:
- Lint, mypy: 0 errors.
- Tests: **557 passed, 1 xfailed** (pre-existing `test_pr_url_reuse_blocked_cross_feature`).
- Coverage: **90.68–90.84%** (80% required).
- Contract: compliant.
- Demo: `uvx showboat verify` passes.

## Demo substance

`docs/demos/wt-fix-localhost/demo.md` has four showboat blocks:

1. `grep -E 'localhost|ip6-' /etc/hosts` — evidence the host declares `::1` for IPv6 loopback.
2. Self-contained Node reproduction: binds an HTTP server to `127.0.0.1` (IPv4 only), then fetches `[::1]:port` (ECONNREFUSED) and `127.0.0.1:port` (200). Proves the IPv4/IPv6 asymmetry deterministically on any host — no backend infra required.
3. `git diff origin/main -- .mcp.json .cloglog/config.yaml mcp-server/src/index.ts` — the three-line fix.
4. `grep -HnE '127\.0\.0\.1|localhost' ...` — post-merge check that every file now defaults to `127.0.0.1`.

## Pre-existing worktree env issues fixed in passing

- `.venv` was python 3.14 from linuxbrew but only partially populated. `uv run pytest` fell back to pyenv's pytest (3.12 shim) and complained about missing `respx`. Fixed with `uv sync --extra dev` — that's what the Makefile/CI expects, not `--group dev` (the `dependency-groups` table carries a subset of the `optional-dependencies.dev` list).

## Follow-ups for main

None from the agent. T-247's review→done transition is the user's board move.
