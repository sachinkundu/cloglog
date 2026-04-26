---
verdict: no_demo
diff_hash: 1e39f6feb7c3f569472f2c69ec45428b599ca53613e6569ac08d46ceaafd02a1
classifier: demo-classifier
generated_at: 2026-04-26T12:30:00Z
---

## Why no demo

Diff is internal agent-lifecycle plumbing: docs spec update, a shell hook
enrichment in `plugins/cloglog/hooks/agent-shutdown.sh` adding a `prs` map
to the inbox event, a launch SKILL prompt template change, a board template
string tweak, and two test files. No HTTP route decorators, no React
components, no MCP `server.tool` registrations, no CLI stdout surface, and
`src/board/templates.py` only edits an internal close-worktree prompt string
consumed agent-to-agent (not user-read CLI output).

Strongest `needs_demo` candidate was the new `pr_merged_notification` event
type, but it's an inter-agent inbox protocol invisible at any user boundary.
If the diff had added a `@router.*` decorator exposing this event over HTTP
or surfaced the `prs` map in a frontend dashboard component, the verdict
would have flipped to `needs_demo`.

## Changed files

- docs/design/agent-lifecycle.md
- plugins/cloglog/hooks/agent-shutdown.sh
- plugins/cloglog/skills/launch/SKILL.md
- src/board/templates.py
- tests/test_agent_lifecycle_pr_signals.py
- tests/test_agent_shutdown_hook.py
