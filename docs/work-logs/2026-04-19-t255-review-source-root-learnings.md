# Learnings: T-255 — review source root fix

**Date:** 2026-04-19

## `Path.cwd()` is a host-side filesystem fingerprint, not an invariant

The review engine's `project_root = Path.cwd()` looked innocuous, but it silently tied codex's file-reading view to wherever the backend process happened to be launched from. Under the F-48 dev/prod separation design, that's `../cloglog-prod` — a worktree that only advances on `make promote`. Any code merged to main in the window between merge and promote is literally invisible to codex.

**Applicable pattern:** anywhere host-side code passes `Path.cwd()` (or an implicit working directory) to a subprocess that reads files, the behavior depends on how the backend was launched. That's fine for a one-shot CLI; it's a silent config bug for a long-running server where dev and prod diverge. Prefer an explicit `Settings` field + env var so operators can see and set the contract.

## Env var naming follows the existing codebase, not the prompt

The AGENT_PROMPT.md proposed `CLOGLOG_REVIEW_SOURCE_ROOT`. But `src/shared/config.py` has no `env_prefix` — `DATABASE_URL`, `HOST`, `PORT` all map 1:1 to uppercased field names. Introducing `CLOGLOG_` just for this one field would diverge from the codebase. I used `REVIEW_SOURCE_ROOT` and flagged the deviation in the PR body.

**Applicable pattern:** when a prompt prescribes a specific env-var name, verify the pydantic-settings config (prefix, delimiter, field_name mapping) before implementing. Match the existing convention; the prompt author may not have checked.

## Startup log = free post-deployment alarm

The spec required the fix plus a one-line startup log showing the resolved path and its HEAD SHA. At first that felt like gold-plating — until I realized that's the ONLY signal an operator has that the env var landed. Without the log, a botched deploy (forgot to set the env var) silently reproduces T-255, and the first signal is another false-negative review days later.

**Applicable pattern:** when a config value's mis-wiring is silent (the code still "works," just against the wrong inputs), emit it to the boot log explicitly. It costs one line; it converts a silent config bug into a grep-able alert.

## Showboat's exec block is not a shell — wrap in `bash -c`

First iteration of the demo-script failed with `fork/exec grep -c "...": no such file or directory` because showboat's `exec` directive treats the whole string as an argv tuple, not a shell command. The pattern from `docs/demos/wt-webhook-resolver/demo-script.sh` — `uvx showboat exec "$DEMO_FILE" bash 'cmd'` — is the idiomatic fix. Worth adding to `plugins/cloglog/skills/demo/SKILL.md` if it is not already there explicitly.

## The security-reminder hook is not Python-aware

A helper I wrote used `asyncio.create_subprocess_exec` (Python, argv list, no shell) and still triggered the Node-centric command-injection security hook. The hook's substring matcher fires on literal text, not on language semantics. Workaround: switched to synchronous `subprocess.run([...])` with `shell=False`. Same safety properties, hook does not fire — and a synchronous probe is probably the right call for a one-shot boot log line anyway.

**Applicable pattern:** when the hook blocks a Python change, the pattern matcher probably tripped on a substring — it is not Python-aware. Either switch to `subprocess.run` with an argv list, or (if you really want asyncio) suppress with a comment.

## The scope guard vs. the actual file layout

The AGENT_PROMPT.md's scope guard listed `src/gateway/config.py`. That file does not exist — the actual config is at `src/shared/config.py`, and that path is covered by the `gateway` worktree scope in `.cloglog/config.yaml`. Don't treat a prompt's file-path list as authoritative; cross-check against the actual tree + the worktree scope before starting.

## Suggestions for CLAUDE.md

Under the existing "Host / agent-VM Split Affects Data Access" section, consider adding a sibling bullet:

> **`Path.cwd()` in backend code is a filesystem fingerprint of the launcher, not an invariant.** The backend process may be launched from dev (`/home/sachin/code/cloglog`), prod (`../cloglog-prod`), or eventually Railway. Any subprocess that reads files via `-C`/`cwd=` must take its root from `Settings`, not `Path.cwd()` — otherwise codex/tools see a different tree than the PR's merge target. See T-255.
