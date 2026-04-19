# T-222 canonical agent lifecycle protocol — single source of truth for F-48

*2026-04-19T11:03:26Z by Showboat 0.6.1*
<!-- showboat-id: 0a5ec528-fdfe-4279-840f-5272a85dedf4 -->

This is a spec-only PR. The deliverable is the canonical lifecycle doc at docs/design/agent-lifecycle.md. The demo verifies the doc exists and covers the six required sections plus the See-also block.

Proof 1 — file exists and is non-empty.

```bash
wc -l docs/design/agent-lifecycle.md
```

```output
381 docs/design/agent-lifecycle.md
```

Proof 2 — the six required sections are present and ordered.

```bash
grep -n '^## [1-6]\.' docs/design/agent-lifecycle.md
```

```output
18:## 1. Exit condition
53:## 2. Shutdown sequence
107:## 3. Inbox contract
176:## 4. MCP discipline
214:## 5. Three-tier shutdown from the main side
286:## 6. Agent session can't self-exit and relaunch
```

Proof 3 — Section 1 pins the authoritative exit condition.

```bash
sed -n '/^## 1\. Exit condition/,/^## 2\. Shutdown sequence/p' docs/design/agent-lifecycle.md | sed -n '1,10p'
```

```output
## 1. Exit condition

**An agent's work is done when `get_my_tasks` returns no task in `backlog`
status for this worktree.** That is the single, authoritative exit signal.

Corollary — things that are NOT exit signals:

| Signal | Why it is not the exit signal |
| --- | --- |
| A single PR merged | The agent may have further `backlog` tasks queued. `pr_merged` only fires the "maybe start next task" flow. |
```

Proof 4 — the See-also block names every follow-up task this spec calls into (T-215, T-216, T-217, T-218, T-219, T-220, T-221, T-243, T-244).

```bash
grep -oE 'T-(215|216|217|218|219|220|221|243|244)' docs/design/agent-lifecycle.md | sort -u
```

```output
T-215
T-216
T-217
T-218
T-219
T-220
T-221
T-243
T-244
```

Proof 5 — the three-tier shutdown section names the concrete numbers T-220 should target.

```bash
grep -nE 'Cooperative timeout|Poll interval|heartbeat_timeout_seconds|180 s|120 s|60 s' docs/design/agent-lifecycle.md
```

```output
231:  - Cooperative timeout: **120 s** from `request_shutdown` to `agent_unregistered`.
232:  - Poll interval on the worktree row: **10 s**.
250:- **When to use.** After tier 1's 120 s timeout elapses without an
262:  **60 s**. Sessions with `last_heartbeat` older than **180 s** (the
263:  `heartbeat_timeout_seconds` setting in `src/shared/config.py`) are marked
279:          server sweep closes the session after 180 s of silence (tier 3)
```

Proof 6 — the doc explicitly forbids awaiting task_status_changed, the signal whose absence caused the 2026-04-19 T-225 deadlock.

```bash
grep -n 'task_status_changed' docs/design/agent-lifecycle.md
```

```output
28:| The task shows `done` on the board | `done` is administrative and user-driven. No push notification fires when a task moves `review` → `done`. `task_status_changed` is emitted on the SSE event bus (dashboard consumer only) and never reaches the worktree inbox. An agent that waits for `done` deadlocks forever. |
163:- `task_status_changed` — including the `review` → `done` transition. This is
```
