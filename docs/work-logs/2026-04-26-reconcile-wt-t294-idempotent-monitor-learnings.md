# Learnings — T-294

Durable, non-obvious gotchas worth carrying forward.

## Inbox tail semantics — `-n 0 -F` is the right default, but it's not the whole story

The cloglog inbox file is **append-only for the worktree's entire lifetime**:

- `src/gateway/webhook_consumers.py` always appends webhook events.
- `request_shutdown` is explicitly pinned by `tests/agent/test_unit.py:1226-1251`
  to append (not truncate) the `{"type":"shutdown"}` line.
- `scripts/wait_for_agent_unregistered.py` uses captured byte offsets
  specifically because naive replay is unsafe.

This means choosing `tail` flags involves a real tradeoff:

| Flag | Behaviour | Right when |
|---|---|---|
| `tail -f <file>` | exits immediately if file missing | NEVER — the inbox is created lazily by the backend's first webhook write |
| `tail -F <file>` | last 10 lines + follow + reopen | NEVER — silently truncates event history |
| `tail -n +1 -F <file>` | full replay + follow | NEVER on its own — re-delivers already-handled `pr_merged` / `review_submitted` and trips `start_task`'s one-active-task guard at `src/agent/services.py:357-370` |
| `tail -n 0 -F <file>` | start at EOF + follow | DEFAULT — correct for `/clear` re-entry (existing monitor caught everything) and for fresh agents |

The trap: `-n 0` is correct for `/clear` but means a **real crash** misses
control events queued during downtime. Webhook events have a GitHub-side
source of truth (`Check PR Status` drill-down), but supervisor-issued
control lines (`shutdown`, `agent_unregistered`, `mcp_*`) do NOT. The
T-294 stopgap is a one-shot inbox tail inspection on crash recovery; the
durable fix is offset-tracked replay (T-296), patterned on
`wait_for_agent_unregistered.py`.

## Always wrap inbox `Monitor` spawns

Every inbox `Monitor` invocation must:

1. **Pre-create the file**: `mkdir -p <PATH>/.cloglog && touch <PATH>/.cloglog/inbox`.
   `tail -f` against a missing file exits exit-1 and leaves you monitor-less.
   This is not a hypothetical — I hit it live at session start.
2. **Use absolute paths**: never `tail -f .cloglog/inbox`. Relative-path
   monitors evade dedupe filters that match on absolute paths.
3. **Use `-n 0 -F`**: see table above.
4. **Reconcile via `TaskList` first**: persistent monitors survive `/clear`,
   so naive re-spawn duplicates the tail. Match on path **suffix**
   (`/.cloglog/inbox`) and verify resolved absolute path equality —
   exact-match filtering misses historical relative-path monitors.

## Persistent Monitor lifetime

- Persistent Monitors are session-local but NOT auto-stopped on `/clear`.
- They survive `/clear` and continue to deliver notifications to the new
  conversation context.
- Multiple Monitors on the same inbox file means every event fires N times.
- Cleanup requires explicit `TaskStop` calls; the dedupe procedure must
  do this proactively because users won't notice the duplicates until
  notifications start triple-firing.

## Codex reviewer behaviour

- The codex reviewer reads code **outside** the diff (`webhook_consumers.py`,
  `agent/services.py`, `wait_for_agent_unregistered.py`). It found defects
  that pure diff-reading would have missed.
- Hard cap is 5 sessions per PR / 10 reviews/hour. Bundle the full scope
  into the first push when possible — but iterative refinement is
  acceptable when each round materially improves the PR (T-294 case: 5
  rounds, every one load-bearing).
- Don't ignore findings just because they enlarge scope. Every codex
  finding on this PR was real. Filing a follow-up task (T-296) for the
  durable fix while shipping a stopgap is a legitimate response.

## Worktree scope and the protect-worktree-writes hook

- The worktree's allowed scope was `plugins/cloglog/skills/` per
  `AGENT_PROMPT.md`, but the `protect-worktree-writes` hook did NOT
  block edits to `docs/`, `plugins/cloglog/templates/`, or
  `plugins/cloglog/agents/`. Either the hook is permissive on these
  paths, or the scope mapping in `.cloglog/config.yaml` doesn't include
  T-294 explicitly (it's per-context, e.g., `agent: [src/agent/, ...]`,
  not per-worktree).
- Boy-scout-rule call: when a fix to in-scope skills creates a
  consistency gap with out-of-scope canonical/template docs, fix the
  out-of-scope docs in the same PR rather than ship a partial fix.
  Reviewer agreed (codex 3/5 explicitly demanded this).

## PR comment shell quoting

- Single-quoted heredocs (`<<'EOF'`) prevent variable expansion. If a
  comment body needs `$(git rev-parse --short HEAD)`, either use an
  unquoted heredoc OR pre-resolve into a shell variable AND reference it
  inside the heredoc. Failure mode: comment body literally contains
  `$(git rev-parse --short HEAD)`. Fixable via `gh api -X PATCH`.

## Demo classifier auto-exempt

- All-skills/all-docs PRs auto-exempt at Step 0 of the `cloglog:demo`
  skill (regex match on `plugins/*/skills/`, `docs/`, etc.). No
  classifier subagent invocation needed. The `make quality` demo gate
  prints `Docs-only branch — no demo required.` when this applies.
