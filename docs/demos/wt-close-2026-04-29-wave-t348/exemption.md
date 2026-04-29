---
verdict: no_demo
diff_hash: 3292e9bfe784522d738e2ca8a49f5a7f8177f2b12fd37fc63ebc503bda163766
classifier: demo-classifier
generated_at: 2026-04-29T17:55:00Z
---

## Why no demo

Diff touches only docs: a new work-log under `docs/work-logs/` and a small text update to `plugins/cloglog/docs/setup-credentials.md` describing the new credential-resolution precedence. No HTTP routes, React components, MCP tool registrations, CLI output, or migrations are changed.

Strongest needs_demo candidate considered: the setup-credentials.md change references a new error string from `gh-app-token.py`, but the script itself isn't modified in this diff.

Counterfactual: if the diff had also modified `plugins/cloglog/scripts/gh-app-token.py` or `launch.sh` heredoc behavior (operator-visible CLI output), it would flip to needs_demo with cli-exec.

## Changed files

- docs/work-logs/2026-04-29-wave-t348-work-log.md
- plugins/cloglog/docs/setup-credentials.md
