#!/usr/bin/env bash
# Demo: Reviewers can now see a single design doc that pins every semantic of the
#       two-stage iterative PR review pipeline T-248 will implement (opencode ×5 → codex ×2).
# Docs-only spec PR for T-261 — no server required.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"
SPEC="docs/design/two-stage-pr-review.md"

# showboat init refuses to overwrite — delete first so `make demo` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Reviewers have a single design doc that pins every semantic of the two-stage iterative PR review pipeline T-248 will implement — opencode (gemma4:e4b) for up to 5 turns, then codex for up to 2 turns, short-circuiting on consensus."

uvx showboat note "$DEMO_FILE" "### The 8 questions and their answers (one-liners)

1. **Per-reviewer loop semantics / consensus** → option (c): explicit \`status: no_further_concerns\` flag OR zero-new-findings (tuple key \`(file, line, title_lower)\`). Worked example in §1.2.
2. **Sequencing** → strictly serial, handled by a single \`WebhookConsumer\` that \`await\`s stage A then stage B (no new event type). §2.
3. **Turn accounting** → new **\`Review\` bounded context** at \`src/review/\` owning the \`pr_review_turns\` table — Gateway cannot own tables per \`docs/ddd-context-map.md\`, so Gateway consumes \`IReviewTurnRegistry\` via Open Host Service. Table keyed \`(pr_url, head_sha, stage, turn_number)\`; idempotency via \`INSERT ... ON CONFLICT DO NOTHING\`; new SHA resets BOTH loops symmetrically. §3.
4. **Identity** → two GitHub App bots (\`cloglog-opencode-reviewer[bot]\`, \`cloglog-codex-reviewer[bot]\`); PEMs at \`~/.agent-vm/credentials/*.pem\` (same precedent as existing codex bot — \`~/.cloglog/credentials\` is for the backend API key only, NOT reviewer tokens); author-skip fix MUST change \`handles()\` to \`event.sender in _REVIEWER_BOTS\` (today's check is \`== _CODEX_BOT\` and \`_BOT_USERNAMES\` is not consulted); visible turn header \`**opencode (gemma4:e4b) — turn 3/5**\`. §4.
5. **Timeouts + startup gate** → opencode 180 s / turn, codex 300 s / turn; 5xx and 409 NOT retried; transient \`ECONNRESET\`/\`ETIMEDOUT\` get one ≥ 2 s backoff; dead opencode never blocks codex at runtime (§5.3). New at boot: \`app.py\` lifespan now probes BOTH binaries (\`is_review_agent_available()\` extended with \`is_opencode_available()\`); registration falls to codex-only / opencode-only / disabled per the §5.4 matrix so a host missing one binary does not spam skip-comments. §5.
6. **Contention / queuing** → one review at a time via existing \`asyncio.Lock\`; implicit FIFO, no dropping/deferring. Rate limit and per-PR cap counted per **session**, not per turn. §6.
7. **Structured output** → additive top-level \`status\` on \`review-schema.json\` PLUS matching \`ReviewResult.status\` field PLUS \`_parse_output\` preserves it through Codex-schema normalization (today \`_parse_output\` rewrites data to \`{verdict, summary, findings}\` only, silently dropping any \`status\` — without all three changes the explicit-consensus branch is a dead branch). §7.
8. **Observability** → \`review_turn_start\` / \`review_turn_end\` / \`review_stage_end\` / \`review_session_end\` structured log lines; metric names reserved; task-card badge extended to \`opencode 2/5\` / \`codex 1/2\`. §8."

uvx showboat note "$DEMO_FILE" "### Proof the artifact exists and is complete"

# Fixed boolean summaries (deterministic across runs).
uvx showboat exec "$DEMO_FILE" bash \
  'test -f docs/design/two-stage-pr-review.md && echo "spec_file_exists=true"'

# Every question 1..8 has a numbered header. Grep for the exact header pattern and emit counts.
uvx showboat exec "$DEMO_FILE" bash \
  'for n in 1 2 3 4 5 6 7 8; do
     c=$(grep -c "^## ${n}\. " docs/design/two-stage-pr-review.md || true)
     echo "question_${n}_header_count=${c}"
   done'

# Acceptance-criteria delta section is present.
uvx showboat exec "$DEMO_FILE" bash \
  'grep -qE "^## What changes in T-248" docs/design/two-stage-pr-review.md && echo "t248_delta_section=present"'

# Spec names the exact files T-248 will touch (not vague handwaving).
uvx showboat exec "$DEMO_FILE" bash \
  'for f in src/gateway/review_engine.py src/gateway/app.py src/shared/config.py src/gateway/github_token.py .github/codex/prompts/review.md .github/codex/review-schema.json src/alembic/versions/ src/review/ docs/ddd-context-map.md; do
     r=$(grep -c "\`${f}\`" docs/design/two-stage-pr-review.md || true)
     echo "names_${f}=$( [ "$r" -gt 0 ] && echo yes || echo no )"
   done'

uvx showboat note "$DEMO_FILE" "### First section of the design doc (for reviewer skim)"
uvx showboat exec "$DEMO_FILE" bash \
  'awk "/^## 1\\. Per-reviewer loop semantics/{found=1} found && /^## 2\\. Sequencing between stages/{exit} found" docs/design/two-stage-pr-review.md | head -40'

uvx showboat verify "$DEMO_FILE"
