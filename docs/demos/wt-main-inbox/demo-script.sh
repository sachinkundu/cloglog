#!/usr/bin/env bash
# Demo: T-253 — close-wave PR webhook events now reach the main agent's inbox
# instead of being silently dropped by the two-tier webhook resolver.
# Called by `make demo` (server + DB already running from worktree infra).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"

DEMO_FILE="docs/demos/$(git rev-parse --abbrev-ref HEAD)/demo.md"
rm -f "$DEMO_FILE"

uvx showboat init "$DEMO_FILE" "Webhook events for close-wave PRs (wt-close-*) now reach the main agent's inbox instead of being silently dropped — the main agent finally sees its own PRs merge."

# -----------------------------------------------------------------------------
# Proof 1 — Settings carries the opt-in field with the right type and default.
# -----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "The main-agent inbox path is opt-in via Settings — unset by default so the pre-T-253 drop behavior is preserved for projects that don't want it."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "main_agent_inbox_path: Path | None" src/shared/config.py'

# -----------------------------------------------------------------------------
# Proof 2 — ResolvedRecipient dataclass + MAIN_AGENT_EVENTS filter are present.
# -----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "The resolver now returns a self-documenting ResolvedRecipient dataclass (worktree_id=None signals the main-agent fallback). MAIN_AGENT_EVENTS is a frozenset that excludes ISSUE_COMMENT — bot comments would otherwise flood the main inbox."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "^class ResolvedRecipient:" src/gateway/webhook_consumers.py'
uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "ISSUE_COMMENT" src/gateway/webhook_consumers.py'

# -----------------------------------------------------------------------------
# Proof 3 — the fallback fires only when config is set AND event type matches.
# -----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "The fallback guard requires BOTH the config path AND a whitelisted event type — without either, the resolver falls through to the existing None return (drop)."
uvx showboat exec "$DEMO_FILE" bash \
  'grep -A1 "main_agent_inbox_path is not None and event.type in MAIN_AGENT_EVENTS" src/gateway/webhook_consumers.py | head -2'

# -----------------------------------------------------------------------------
# Proof 4a — env unset: Settings.main_agent_inbox_path is None -> fallback OFF.
# -----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "With MAIN_AGENT_INBOX_PATH unset, Settings loads main_agent_inbox_path as None — the third fallback is disabled and behavior matches the pre-T-253 baseline."
uvx showboat exec "$DEMO_FILE" bash \
  'env -u MAIN_AGENT_INBOX_PATH uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"main_agent_inbox_path:\", s.main_agent_inbox_path)"'

# -----------------------------------------------------------------------------
# Proof 4b — env set: Settings.main_agent_inbox_path is a Path -> fallback ON.
# -----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "With MAIN_AGENT_INBOX_PATH set, Settings picks it up as a Path — operators opt in by adding this one line to their .env (or setting it in their deployment environment)."
uvx showboat exec "$DEMO_FILE" bash \
  'MAIN_AGENT_INBOX_PATH=/home/sachin/code/cloglog/.cloglog/inbox uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"main_agent_inbox_path:\", s.main_agent_inbox_path)"'

# -----------------------------------------------------------------------------
# Proof 5 — the five T-253 tests (TestMainAgentFallback) all pass.
# -----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "Five new T-253 integration tests cover both paths of the fallback: on + off, the regression guard (worktree routing still wins when it matches), and the ISSUE_COMMENT filter."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/gateway/test_webhook_consumers.py::TestMainAgentFallback -q --no-header 2>&1 | grep -oE "[0-9]+ passed"'

# -----------------------------------------------------------------------------
# Proof 6 — full webhook-consumer suite still green (no regressions).
# -----------------------------------------------------------------------------
uvx showboat note "$DEMO_FILE" "The full webhook-consumers test file still passes end-to-end, including the five new tests and the pre-existing resolver/message/inbox coverage."
uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/gateway/test_webhook_consumers.py -q --no-header 2>&1 | grep -oE "[0-9]+ passed"'

uvx showboat verify "$DEMO_FILE"
