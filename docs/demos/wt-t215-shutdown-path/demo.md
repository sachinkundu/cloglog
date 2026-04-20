# Cooperative shutdown now reaches worktree agents: request_shutdown writes to <worktree_path>/.cloglog/inbox — the same file every agent already monitors — instead of the dead /tmp/cloglog-inbox-{id} path that blocked T-220 three-tier shutdown.

*2026-04-20T11:15:24Z by Showboat 0.6.1*
<!-- showboat-id: a534b4af-adf9-42d5-acf6-f186ce45bcda -->

Proof 1 — the legacy /tmp/cloglog-inbox- write path is completely removed from src/. Count of matches under src/:

```bash
grep -rn '/tmp/cloglog-inbox-' src/ | wc -l
```

```output
0
```

Proof 2 — request_shutdown now builds the inbox path from worktree.worktree_path. Expected 1 line in src/agent/services.py:

```bash
grep -cE "Path\(worktree\.worktree_path\) / \"\.cloglog\" / \"inbox\"" src/agent/services.py
```

```output
1
```

Proof 3 — docs/design/agent-lifecycle.md's legacy note now reflects the completed migration (phrase 'is removed' present):

```bash
grep -c 'is removed' docs/design/agent-lifecycle.md
```

```output
1
```

Proof 4 — live run. A worktree was registered at /tmp/demo-t215-worktree and POST /agents/{id}/request-shutdown was invoked. The file the backend wrote (<worktree>/.cloglog/inbox) is frozen at docs/demos/wt-t215-shutdown-path/captured-inbox.txt. It contains exactly one line whose JSON type is 'shutdown':

```bash
wc -l < docs/demos/wt-t215-shutdown-path/captured-inbox.txt
```

```output
1
```

```bash
python3 -c 'import json; print(json.loads(open("docs/demos/wt-t215-shutdown-path/captured-inbox.txt").readline())["type"])'
```

```output
shutdown
```

Proof 5 — full captured JSON body shows the shutdown message the agent will act on:

```bash
cat docs/demos/wt-t215-shutdown-path/captured-inbox.txt
```

```output
{"type": "shutdown", "message": "SHUTDOWN REQUESTED: The master agent has requested this worktree to shut down. Finish your current work, generate shutdown artifacts (work-log.md and learnings.md in shutdown-artifacts/), call unregister_agent, and exit."}
```
