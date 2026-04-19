#!/usr/bin/env bash
# Demo: T-222 canonical agent lifecycle protocol doc (F-48 Wave A).
# Called by `make demo`. This is a docs-only PR — the canonical doc IS the
# deliverable, so the demo proves (a) the file exists at the expected path,
# (b) each of the six required sections is present and in order, and (c) the
# "See also" follow-up block lists all of T-215/T-216/T-218/T-219/T-220/T-221/
# T-243/T-244.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

DEMO_FILE="docs/demos/wt-f48-spec/demo.md"
DOC="docs/design/agent-lifecycle.md"

uvx showboat init "$DEMO_FILE" "T-222 canonical agent lifecycle protocol — single source of truth for F-48"

uvx showboat note "$DEMO_FILE" "This is a spec-only PR. The deliverable is the canonical lifecycle doc at docs/design/agent-lifecycle.md. The demo verifies the doc exists and covers the six required sections plus the See-also block."

uvx showboat note "$DEMO_FILE" "Proof 1 — file exists and is non-empty."
uvx showboat exec "$DEMO_FILE" bash \
  "wc -l docs/design/agent-lifecycle.md"

uvx showboat note "$DEMO_FILE" "Proof 2 — the six required sections are present and ordered."
uvx showboat exec "$DEMO_FILE" bash \
  "grep -n '^## [1-6]\\.' docs/design/agent-lifecycle.md"

uvx showboat note "$DEMO_FILE" "Proof 3 — Section 1 pins the authoritative exit condition."
uvx showboat exec "$DEMO_FILE" bash \
  "sed -n '/^## 1\\. Exit condition/,/^## 2\\. Shutdown sequence/p' docs/design/agent-lifecycle.md | sed -n '1,10p'"

uvx showboat note "$DEMO_FILE" "Proof 4 — the See-also block names every follow-up task this spec calls into (T-215, T-216, T-217, T-218, T-219, T-220, T-221, T-243, T-244)."
uvx showboat exec "$DEMO_FILE" bash \
  "grep -oE 'T-(215|216|217|218|219|220|221|243|244)' docs/design/agent-lifecycle.md | sort -u"

uvx showboat note "$DEMO_FILE" "Proof 5 — the three-tier shutdown section names the concrete numbers T-220 should target."
uvx showboat exec "$DEMO_FILE" bash \
  "grep -nE 'Cooperative timeout|Poll interval|heartbeat_timeout_seconds|180 s|120 s|60 s' docs/design/agent-lifecycle.md"

uvx showboat note "$DEMO_FILE" "Proof 6 — the doc explicitly forbids awaiting task_status_changed, the signal whose absence caused the 2026-04-19 T-225 deadlock."
uvx showboat exec "$DEMO_FILE" bash \
  "grep -n 'task_status_changed' docs/design/agent-lifecycle.md"

uvx showboat verify "$DEMO_FILE"
