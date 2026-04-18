#!/usr/bin/env bash
# Demo: MCP update_task_status guidance + github-bot SKILL.md now describe
# webhook-driven inbox events instead of a /loop polling cycle.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../scripts/worktree-ports.sh"

DEMO_FILE="docs/demos/$(git rev-parse --abbrev-ref HEAD)/demo.md"
DEMO_DIR="docs/demos/$(git rev-parse --abbrev-ref HEAD)"

# Build the MCP server once so the harness can import from dist/ — showboat
# exec runs a command directly, not via `&&` chains.
(cd mcp-server && npm run build --silent >/dev/null)

uvx showboat init "$DEMO_FILE" \
  "Agents moving a task to review are now told to watch their inbox for webhook events, not to start a 5-minute polling loop."

# ── 1. New MCP update_task_status guidance text ─────────────────────────────

uvx showboat note "$DEMO_FILE" \
"## 1. New MCP tool response text

The MCP server's \`update_task_status\` tool returns a guidance string to the
agent after moving a task to \`review\`. We call the tool handler with a mock
HTTP client (no live backend) and print the response body verbatim, so the
exact text the agent will see is captured below.

\`mcp-server/scripts/demo-update-task-status.mjs\` is a thin harness built
for this demo — it wires a mocked \`CloglogClient\` to \`createServer\`,
invokes the \`update_task_status\` tool with \`status=review\` and a
sample PR URL, and prints the single text block."

uvx showboat exec "$DEMO_FILE" bash \
  "node mcp-server/scripts/demo-update-task-status.mjs"

# ── 2. Old /loop instruction is gone ───────────────────────────────────────

uvx showboat note "$DEMO_FILE" \
"## 2. The old \`/loop 5m\` instruction is gone

Before this change the response contained a \`/loop 5m Check PR #…\`
instruction. Grep confirms no such line is produced any more — neither in
the server source nor in the github-bot skill."

uvx showboat exec "$DEMO_FILE" bash \
  "echo 'server.ts mentions of /loop 5m:' && grep -c '/loop 5m' mcp-server/src/server.ts || true"

uvx showboat exec "$DEMO_FILE" bash \
  "echo 'SKILL.md mentions of /loop 5m (expect 0):' && grep -c '/loop 5m' plugins/cloglog/skills/github-bot/SKILL.md || true"

uvx showboat exec "$DEMO_FILE" bash \
  "echo 'test suite mentions of /loop 5m (should appear only in a NOT-contain assertion):' && grep -n '/loop 5m' mcp-server/tests/server.test.ts || true"

# ── 3. Rewritten github-bot SKILL.md sections ──────────────────────────────

uvx showboat note "$DEMO_FILE" \
"## 3. Rewritten \`github-bot\` skill

The post-PR steps and the PR-state section of the skill now tell agents to
keep their inbox \`Monitor\` running and to respond to webhook events —
\`review_submitted\`, \`ci_failed\`, \`pr_merged\`, \`pr_closed\` — instead
of starting a \`/loop\` polling cycle. Rule 5 in the Rules list has also
been reworded so that the \"atomic with PR creation\" pair is board update
+ inbox monitor, not board update + polling loop."

uvx showboat exec "$DEMO_FILE" bash \
  "awk '/^After creating the PR/,/See \\[PR Event Inbox\\]/' plugins/cloglog/skills/github-bot/SKILL.md"

uvx showboat exec "$DEMO_FILE" bash \
  "awk '/^### PR Event Inbox/,/\\*\\*Offline fallback:\\*\\*/' plugins/cloglog/skills/github-bot/SKILL.md"

uvx showboat exec "$DEMO_FILE" bash \
  "grep -n 'Inbox monitor is atomic' plugins/cloglog/skills/github-bot/SKILL.md"

# ── 4. Unit tests cover the new behavior ───────────────────────────────────

uvx showboat note "$DEMO_FILE" \
"## 4. Unit tests cover the new behavior

\`mcp-server/tests/server.test.ts\` has been updated so the existing
\"update_task_status includes loop instruction …\" test now asserts the
response contains \`webhook\`, \`inbox\`, \`review_submitted\`,
\`ci_failed\`, \`pr_merged\` and explicitly does **not** contain
\`/loop 5m\`. The negative test for non-review statuses also asserts
the absence of \`webhook\` and \`inbox\`. All 49 MCP server tests pass."

uvx showboat exec "$DEMO_FILE" bash \
  "cd mcp-server && npx vitest run --reporter=basic tests/server.test.ts >/tmp/vitest-out.txt 2>&1 && grep -E '^(Test Files|     Tests)' /tmp/vitest-out.txt | sed 's/(\\([0-9]\\+\\)ms)//g; s/ [0-9]\\+ms\\$//'"

uvx showboat verify "$DEMO_FILE"
