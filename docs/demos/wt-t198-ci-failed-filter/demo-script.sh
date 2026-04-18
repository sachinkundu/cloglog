#!/usr/bin/env bash
# Demo: AgentNotifierConsumer no longer emits false ci_failed notifications for
# check_run webhooks whose conclusion is null (pending) or terminal non-failure.
# Called by `make demo`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_FILE="docs/demos/$BRANCH/demo.md"
PROBE="docs/demos/$BRANCH/probe.py"

uvx showboat init "$DEMO_FILE" \
  "Agents no longer receive false ci_failed notifications when GitHub fires check_run events with a null (pending) conclusion."

uvx showboat note "$DEMO_FILE" \
  "Setup: the bug lived in AgentNotifierConsumer._build_message. The probe script drives that method directly with representative GitHub check_run payloads and prints the would-be inbox message (or 'None' when the event is silently ignored)."

uvx showboat note "$DEMO_FILE" \
  "Before the fix: a check_run with conclusion:null produced a ci_failed message. GitHub fires this event every time a check is queued, so every agent got a false CI_FAILED page on every PR push."

uvx showboat note "$DEMO_FILE" \
  "After the fix: only GitHub's terminal non-success conclusions {failure, cancelled, timed_out, action_required, stale} produce a ci_failed notification. Everything else (null, success, neutral, skipped) is silently ignored."

uvx showboat note "$DEMO_FILE" \
  "Case 1 — conclusion: null (the bug scenario). Expect: None."
uvx showboat exec "$DEMO_FILE" bash "uv run python $PROBE null"

uvx showboat note "$DEMO_FILE" \
  "Case 2 — conclusion: success. Expect: None."
uvx showboat exec "$DEMO_FILE" bash "uv run python $PROBE success"

uvx showboat note "$DEMO_FILE" \
  "Case 3 — conclusion: neutral (terminal, not a failure). Expect: None."
uvx showboat exec "$DEMO_FILE" bash "uv run python $PROBE neutral"

uvx showboat note "$DEMO_FILE" \
  "Case 4 — conclusion: skipped (terminal, not a failure). Expect: None."
uvx showboat exec "$DEMO_FILE" bash "uv run python $PROBE skipped"

uvx showboat note "$DEMO_FILE" \
  "Case 5 — conclusion: failure. Expect: ci_failed message for the agent."
uvx showboat exec "$DEMO_FILE" bash "uv run python $PROBE failure"

uvx showboat note "$DEMO_FILE" \
  "Case 6 — conclusion: timed_out (another terminal failure). Expect: ci_failed message."
uvx showboat exec "$DEMO_FILE" bash "uv run python $PROBE timed_out"

uvx showboat note "$DEMO_FILE" \
  "Case 7 — conclusion: cancelled (terminal failure). Expect: ci_failed message."
uvx showboat exec "$DEMO_FILE" bash "uv run python $PROBE cancelled"

uvx showboat verify "$DEMO_FILE"
