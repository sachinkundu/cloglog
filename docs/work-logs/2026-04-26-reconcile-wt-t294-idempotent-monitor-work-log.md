# Work Log — T-294 Idempotent Inbox Monitor

**Branch:** `wt-t294-idempotent-monitor`
**PR:** https://github.com/sachinkundu/cloglog/pull/222 (merged)
**Worktree ID:** `3aa234ad-e564-4c72-99d5-cbfe2459b7b5`
**Task ID:** `905b4e22-7291-4c63-9bf7-1b4672f77b0b`
**Follow-up filed:** T-296 — Offset-tracked inbox replay for crash recovery

## Scope

Make `/cloglog setup` and the launch skill's agent-prompt template idempotent
on re-entry: exactly one inbox `Monitor` per agent process, even after
`/clear`. Persistent monitors survived `/clear` and accumulated duplicate
tails; every inbox event triple-fired into the main agent.

## Commits

1. `4b2d54b` fix(skills): idempotent inbox monitor in setup + launch (T-294)
   — Initial implementation. `TaskList` reconciliation: reuse on one-match,
     spawn on zero, keep-oldest + `TaskStop` rest on two-or-more.
2. `6c9f355` fix(skills): dedupe across relative-path monitors (codex)
   — Codex 1/5: `github-bot/SKILL.md` crash-recovery still used relative
     `tail -f .cloglog/inbox`; my exact-match filter would miss it. Switched
     to absolute path everywhere; dedupe filter now suffix-matches
     `/.cloglog/inbox` for historical relative-path monitors.
3. `351b697` fix(skills): pre-create inbox + tail -F to survive missing file
   — Codex 2/5: `tail -f` exits immediately on missing file; the lifecycle
     spec defers inbox creation to the backend's first webhook write. I hit
     this exact bug live at session start (Monitor failed exit 1 until I
     touched the file). Added `mkdir -p && touch && tail -F` prelude to all
     three spawn sites.
4. `f5e6e05` fix(skills+docs): tail -n +1 -F + propagate to canonical sites
   — Codex 3/5 (MEDIUM): bare `tail -F` only emits last 10 lines. Switched
     to `tail -n +1 -F`. (HIGH): three other authoritative docs still taught
     the old form; updated `docs/design/agent-lifecycle.md`,
     `plugins/cloglog/templates/claude-md-fragment.md`, and
     `plugins/cloglog/agents/worktree-agent.md` so the bug can't be
     re-introduced through canonical channels.
5. `55d5961` fix(skills+docs): tail -n 0 -F (start at EOF) + Check PR Status
   — Codex 4/5 reversed direction on commit 4: replaying from line 1 is
     unsafe because the inbox is append-only for the worktree's lifetime;
     re-delivering historical `pr_merged`/`review_submitted` events would
     trip `start_task`'s one-active-task guard. Switched all six sites to
     `tail -n 0 -F`. Documented that `Check PR Status` is the reconciliation
     channel for missed events, not `tail` history.
6. `5d86baf` fix(skills): one-shot inbox tail inspection for crash recovery
   — Codex 5/5: `tail -n 0 -F` correctly handles `/clear` re-entry but
     skips control events queued during a real crash — `shutdown` (worktree)
     and `agent_unregistered` (supervisor) have no GitHub-side fallback like
     webhook events do. Added a clearly-scoped "Reconcile control events on
     crash recovery" step to `setup/SKILL.md` and `github-bot/SKILL.md`:
     normal session start skips it; on crash recovery, `Read` the inbox tail
     one-shot and act on queued control lines. Filed T-296 for the durable
     fix (offset-tracked replay analogous to
     `scripts/wait_for_agent_unregistered.py`).

## Files touched

- `plugins/cloglog/skills/setup/SKILL.md` (in scope)
- `plugins/cloglog/skills/launch/SKILL.md` (in scope)
- `plugins/cloglog/skills/github-bot/SKILL.md` (in scope, for crash recovery prose)
- `plugins/cloglog/agents/worktree-agent.md` (out of scope — boy-scout fix to keep canonical sites in sync)
- `plugins/cloglog/templates/claude-md-fragment.md` (out of scope — same reason; this is what `/cloglog init` injects)
- `docs/design/agent-lifecycle.md` (out of scope — explicit canonical Monitor invocation spec)

`protect-worktree-writes` hook did not block the out-of-scope edits, so
they were carried in the same PR rather than fragmented.

## Quality gate

`make quality` passed at every commit boundary. 857 backend tests + 54
invariant pin tests; lint, mypy, contract, demo, MCP server build all
green. Demo skill auto-exempted at Step 0 (every changed file is on the
developer-infrastructure allowlist — `plugins/*/skills/`, `plugins/*/agents/`,
`plugins/*/templates/`, `docs/`).

## Code review

Five rounds with `cloglog-codex-reviewer[bot]` (5/5 sessions, hit cap on
the final commit). Every finding was real and load-bearing — none were
nits. Each round materially shaped the final design:

- 1/5 → discovered the relative-path monitor blind spot in github-bot
- 2/5 → discovered the missing-file bug (live-verified at session start)
- 3/5 → forced propagation to canonical/template docs (HIGH severity)
- 4/5 → reversed direction on `-n +1` (would break `start_task`)
- 5/5 → carved out crash-recovery semantics + filed T-296

The PR ended up much stronger than the initial commit. The reviewer's
willingness to read code outside the diff (`webhook_consumers.py`,
`agent/services.py`, `wait_for_agent_unregistered.py`) caught defects
that pure diff-reading would have missed.
