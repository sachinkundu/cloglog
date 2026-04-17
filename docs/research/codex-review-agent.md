# Research: OpenAI Codex CLI as Automated PR Reviewer

**Date:** 2026-04-14
**Status:** Research complete
**Sources:** OpenAI developer documentation, OpenAI Cookbook, GitHub repositories, community guides

---

## 1. Codex CLI Invocation for Code Review

### Installation

```bash
npm install -g @openai/codex
# or
brew install --cask codex
```

### The Core Command for PR Review

```bash
# Pipe a diff into Codex with a review prompt and get structured JSON output
git diff origin/main...HEAD | codex exec \
  --full-auto \
  --output-schema ./codex-review-schema.json \
  -o review-output.json \
  --ephemeral \
  --skip-git-repo-check \
  "Review this code change. Focus on correctness, security, and maintainability bugs."
```

### Key Flags Reference

| Flag | Purpose | Notes |
|------|---------|-------|
| `--full-auto` | No human approval prompts. Sets approval to `on-request` and sandbox to `workspace-write`. | Required for automation. |
| `--json` | Emit JSONL event stream to stdout. | Use for real-time progress monitoring. |
| `-o, --output-last-message <path>` | Write final assistant message to a file. | Use with `--output-schema` for structured review output. |
| `--output-schema <path>` | Enforce structured JSON output conforming to a JSON Schema. | **This is the key flag for structured reviews.** |
| `--ephemeral` | Don't persist session files to disk. | Use in CI/webhook contexts. |
| `-C, --cd <path>` | Set working directory before processing. | Point to the repo checkout. |
| `-s, --sandbox <mode>` | `read-only`, `workspace-write`, `danger-full-access` | Use `read-only` for reviews (no file changes needed). |
| `--skip-git-repo-check` | Allow running outside a git repo. | Needed if reviewing a diff without a full checkout. |
| `-m, --model <model>` | Override model. | OpenAI recommends `gpt-5.2-codex` for code review. |
| `--dangerously-bypass-approvals-and-sandbox` / `--yolo` | No sandbox, no approvals at all. | Only in fully isolated CI VMs. |
| `-i, --image <path>` | Attach images to prompt. | Potentially useful for screenshot-based UI reviews. |
| `--color never` | Disable ANSI colors. | Use in CI for clean log output. |

### Stdin Patterns

Codex exec supports prompt-plus-stdin, which is critical for reviews:

```bash
# Pipe diff as context, pass review instructions as the prompt argument
git diff origin/main...HEAD | codex exec "Review this diff for bugs"

# Full prompt from stdin (use - sentinel)
cat review-prompt.md | codex exec -

# Pipe test output for failure analysis
npm test 2>&1 | codex exec "Summarize failures and propose fixes"
```

### Timeout Configuration

Set in `~/.codex/config.toml` or `.codex/config.toml` in the project:

```toml
stream_idle_timeout_ms = 300000  # 5 minutes (default)
```

No CLI flag for timeout; it is config-only.

### Network and Sandbox Restrictions

In `workspace-write` mode (the default with `--full-auto`), network access is disabled by default. For a review-only workflow where Codex should not modify files:

```bash
codex exec --sandbox read-only "Review this diff"
```

Advanced sandbox config in `.codex/config.toml`:

```toml
[sandbox_workspace_write]
network_access = false

[shell_environment_policy]
inherit = "none"
include_only = ["PATH", "HOME"]
exclude = ["AWS_*", "AZURE_*", "OPENAI_*"]
```

---

## 2. AGENTS.md Support

### Yes, Codex CLI Reads AGENTS.md Automatically

Codex discovers and loads AGENTS.md files before every session using a three-tier hierarchy:

1. **Global:** `~/.codex/AGENTS.override.md` > `~/.codex/AGENTS.md`
2. **Project:** Walks from git root to CWD, checking each directory for `AGENTS.override.md` > `AGENTS.md` > fallback filenames
3. **Merge order:** Files concatenate root-to-CWD; closer files override earlier guidance

**Size limit:** Combined AGENTS.md content is capped at `project_doc_max_bytes` (default 32 KiB).

### AGENTS.md vs CLAUDE.md

| Aspect | AGENTS.md (Codex) | CLAUDE.md (Claude Code) |
|--------|-------------------|------------------------|
| Discovery | Git root to CWD, per-directory | Git root, plus `~/.claude/` |
| Override mechanism | `AGENTS.override.md` variant | No override variant |
| Fallback filenames | Configurable via `project_doc_fallback_filenames` | Fixed (`CLAUDE.md`) |
| Size limit | 32 KiB default, configurable | Implicit (context window) |
| Review-specific section | `## Review guidelines` (recognized by Codex Cloud) | No special section |

### Review Guidelines Section

Codex Cloud (and the GitHub integration) specifically looks for a `## Review guidelines` section in AGENTS.md. When found, Codex applies these guidelines during PR reviews. The closest AGENTS.md to each changed file provides the guidance.

```markdown
## Review guidelines

- Focus on correctness and security; ignore style/formatting
- All new API endpoints must have auth middleware
- Don't log PII
- Database queries must use parameterized statements
- Cross-context imports are forbidden (DDD boundary violation)
- All public functions need type annotations
```

### Configuring Fallback Filenames

To make Codex also read CLAUDE.md (useful for the dual-agent setup):

```toml
# ~/.codex/config.toml or .codex/config.toml
project_doc_fallback_filenames = ["CLAUDE.md", "TEAM_GUIDE.md"]
```

This means Codex will check: `AGENTS.override.md` > `AGENTS.md` > `CLAUDE.md` > `TEAM_GUIDE.md` in each directory.

---

## 3. Structured JSON Output for Reviews

### The Output Schema

Use `--output-schema` to enforce structured review output. Here is the complete schema from OpenAI's cookbook:

```json
{
  "type": "object",
  "properties": {
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string",
            "maxLength": 80
          },
          "body": {
            "type": "string",
            "minLength": 1
          },
          "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
          },
          "priority": {
            "type": "integer",
            "minimum": 0,
            "maximum": 3
          },
          "code_location": {
            "type": "object",
            "properties": {
              "absolute_file_path": {
                "type": "string",
                "minLength": 1
              },
              "line_range": {
                "type": "object",
                "properties": {
                  "start": { "type": "integer", "minimum": 1 },
                  "end": { "type": "integer", "minimum": 1 }
                },
                "required": ["start", "end"],
                "additionalProperties": false
              }
            },
            "required": ["absolute_file_path", "line_range"],
            "additionalProperties": false
          }
        },
        "required": ["title", "body", "confidence_score", "priority", "code_location"],
        "additionalProperties": false
      }
    },
    "overall_correctness": {
      "type": "string",
      "enum": ["patch is correct", "patch is incorrect"]
    },
    "overall_explanation": {
      "type": "string",
      "minLength": 1
    },
    "overall_confidence_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 1
    }
  },
  "required": ["findings", "overall_correctness", "overall_explanation", "overall_confidence_score"],
  "additionalProperties": false
}
```

**Priority levels:** 0 = informational, 1 = low, 2 = medium, 3 = critical

### JSONL Event Stream

When using `--json`, Codex emits newline-delimited JSON events:

```jsonl
{"type":"thread.started","thread_id":"0199a213-..."}
{"type":"turn.started"}
{"type":"item.started", ...}
{"type":"item.completed", ...}
{"type":"turn.completed", ...}
```

Event types: `thread.started`, `turn.started`, `turn.completed`, `turn.failed`, `item.started`, `item.updated`, `item.completed`, `error`.

### Combining Flags for CI

```bash
codex exec \
  --json \
  --output-schema ./review-schema.json \
  -o review-output.json \
  --ephemeral \
  --sandbox read-only \
  --color never \
  "Review the changes in this PR" < <(git diff origin/main...HEAD)
```

- `--json` gives you real-time progress on stderr
- `--output-schema` enforces the structured JSON format
- `-o` writes the final structured review to a file
- The review JSON in the output file conforms to the schema

---

## 4. Review Prompt Best Practices

### OpenAI's Recommended Review Prompt

From the official cookbook:

> "You are acting as a reviewer for a proposed code change made by another engineer. Focus on issues that impact correctness, performance, security, maintainability, or developer experience. Flag only actionable issues introduced by the pull request."
>
> Additional instructions:
> - Provide brief, direct explanations citing affected files and line ranges
> - Prioritize severe issues over minor comments
> - Generate an overall correctness verdict ("patch is correct" or "patch is incorrect")
> - Include a confidence score between 0 and 1
> - Ensure file citations and line numbers are precisely accurate

### Prompt Engineering for Reducing False Positives

Based on research into LLM code review prompting (including Meta's "semi-formal reasoning" technique that achieved 93% accuracy):

1. **Specify what NOT to flag:** "Do not comment on code style, formatting, naming conventions, or missing documentation. Only flag functional bugs, security issues, and logic errors."

2. **Require evidence:** "For each finding, trace the execution path that leads to the bug. Do not flag issues based on function names or superficial patterns alone."

3. **Use confidence thresholds:** Post-process the output to filter findings below a confidence threshold (e.g., 0.7). This is easy with structured JSON output.

4. **Scope to the diff:** "Only review code that was added or modified in this diff. Do not flag pre-existing issues in unchanged code."

5. **Include few-shot examples:** If using a prompt file, include 2-3 examples of good findings and 2-3 examples of things that should NOT be flagged.

### Recommended Prompt for cloglog

```markdown
You are reviewing a pull request for a Python/FastAPI + React/TypeScript project
that follows Domain-Driven Design with strict bounded context boundaries.

## What to review

Focus ONLY on these categories:
- **Correctness bugs:** Logic errors, wrong return types, missing error handling,
  race conditions, off-by-one errors
- **Security issues:** SQL injection, auth bypass, secrets in code, XSS
- **DDD boundary violations:** Importing from another context's internals
  (board/, agent/, document/, gateway/ are separate contexts)
- **API contract drift:** Endpoint signatures that don't match the OpenAPI contract
- **Pydantic schema gaps:** Fields missing from Update schemas (causes silent data loss
  with model_dump(exclude_unset=True))

## What NOT to review

Do NOT comment on:
- Code style, formatting, or naming (ruff handles this)
- Type annotation completeness (mypy handles this)
- Test coverage gaps (unless a bug is clearly untested)
- Documentation quality
- Import ordering

## Output requirements

- Flag only issues introduced by this diff, not pre-existing problems
- For each finding, explain the concrete failure scenario
- Priority 3 = will cause data loss or security breach
- Priority 2 = will cause incorrect behavior under normal conditions
- Priority 1 = edge case that could cause issues
- Priority 0 = suggestion for improvement (use sparingly)
- If the patch is correct, say so. Do not invent problems.
```

---

## 5. Running Codex CLI as a Subprocess

### From Python

**Option A: subprocess (simple, reliable)**

```python
import subprocess
import json

def run_codex_review(diff: str, prompt_file: str, schema_file: str) -> dict:
    result = subprocess.run(
        [
            "codex", "exec",
            "--full-auto",
            "--output-schema", schema_file,
            "--ephemeral",
            "--sandbox", "read-only",
            "--color", "never",
            "--skip-git-repo-check",
            "-C", "/path/to/repo",
            "-"  # read prompt from stdin
        ],
        input=f"Review this diff:\n\n{diff}",
        capture_output=True,
        text=True,
        timeout=300,
        env={
            "CODEX_API_KEY": "...",
            "PATH": "/usr/bin:/usr/local/bin",
            "HOME": os.environ["HOME"],
        }
    )

    if result.returncode != 0:
        raise RuntimeError(f"Codex failed: {result.stderr}")

    return json.loads(result.stdout)
```

**Key points:**
- `codex exec` does NOT require a TTY. It is designed for non-interactive use.
- Progress streams to stderr, final output to stdout.
- `--json` makes stdout a JSONL stream (use for real-time monitoring, not for final output parsing).
- `-o <file>` writes the final message to a file (alternative to capturing stdout).
- With `--output-schema`, stdout contains the structured JSON conforming to the schema.

**Option B: Codex Python SDK (experimental)**

```python
from codex_app_server import Codex

with Codex() as codex:
    thread = codex.thread_start(model="gpt-5.2-codex")
    result = thread.run("Review this diff: ...")
    print(result.final_response)
```

The Python SDK requires Python 3.10+ and a local checkout of the Codex repo. It controls the local app-server over JSON-RPC. It is marked experimental. **Recommendation: use subprocess for now.**

**Option C: codex-python-sdk (community wrapper)**

A community package (`openai-codex-sdk` on PyPI) wraps subprocess management with an ergonomic API. Worth evaluating but not officially supported.

### TTY Requirements

- `codex exec`: No TTY required. Designed for pipes and CI.
- `codex` (interactive): Requires TTY for the TUI.
- `codex fork`: Currently requires TTY (a limitation; there is an open issue #11750 requesting headless fork support).

### Process Model

Codex CLI launches a local app-server process that communicates with OpenAI's API. When using `codex exec`, this is transparent -- the CLI handles startup and shutdown. The app-server can also be run standalone (`codex app-server`) and connected to via WebSocket for more complex orchestration.

---

## 6. CI/CD Integration Patterns

### Pattern A: GitHub Action (Official)

OpenAI provides `openai/codex-action@v1`. Complete PR review workflow:

```yaml
name: Codex PR Review
on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v5
        with:
          ref: refs/pull/${{ github.event.pull_request.number }}/merge

      - name: Fetch base and head
        run: |
          git fetch --no-tags origin \
            ${{ github.event.pull_request.base.ref }} \
            +refs/pull/${{ github.event.pull_request.number }}/head

      - name: Run Codex Review
        id: codex
        uses: openai/codex-action@v1
        with:
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          prompt-file: .github/codex/prompts/review.md
          output-file: codex-output.json
          sandbox: read-only
          safety-strategy: drop-sudo

      - name: Post review comment
        if: steps.codex.outputs.final-message != ''
        uses: actions/github-script@v7
        with:
          github-token: ${{ github.token }}
          script: |
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.payload.pull_request.number,
              body: process.env.CODEX_MSG,
            });
        env:
          CODEX_MSG: ${{ steps.codex.outputs.final-message }}
```

### Pattern B: Webhook + Self-Hosted Runner (Our Use Case)

For cloglog where we want a webhook-triggered review bot:

```bash
#!/usr/bin/env bash
# review-pr.sh — called by webhook handler when PR is opened/updated

PR_NUMBER="$1"
REPO_DIR="/path/to/cloglog"

cd "$REPO_DIR"
git fetch origin
git checkout "refs/pull/${PR_NUMBER}/merge"

# Generate the diff
DIFF=$(git diff "origin/main...HEAD")

# Run Codex review with structured output
echo "$DIFF" | codex exec \
  --full-auto \
  --output-schema "$REPO_DIR/.github/codex/review-schema.json" \
  -o /tmp/review-output.json \
  --ephemeral \
  --sandbox read-only \
  --color never \
  -C "$REPO_DIR" \
  -m gpt-5.2-codex \
  "$(cat "$REPO_DIR/.github/codex/prompts/review.md")"

# Post findings as inline PR comments via gh CLI
jq -c '.findings[]' /tmp/review-output.json | while read -r finding; do
  file=$(echo "$finding" | jq -r '.code_location.absolute_file_path')
  line=$(echo "$finding" | jq -r '.code_location.line_range.end')
  body=$(echo "$finding" | jq -r '"\(.title)\n\n\(.body)\n\nConfidence: \(.confidence_score) | Priority: \(.priority)"')

  gh api "repos/OWNER/REPO/pulls/${PR_NUMBER}/comments" \
    --method POST \
    -f body="$body" \
    -f commit_id="$(git rev-parse HEAD)" \
    -f path="$file" \
    -F line="$line" \
    -f side="RIGHT"
done

# Post overall summary
VERDICT=$(jq -r '.overall_correctness' /tmp/review-output.json)
EXPLANATION=$(jq -r '.overall_explanation' /tmp/review-output.json)
CONFIDENCE=$(jq -r '.overall_confidence_score' /tmp/review-output.json)

gh pr comment "$PR_NUMBER" --body "## Codex Review

**Verdict:** ${VERDICT}
**Confidence:** ${CONFIDENCE}

${EXPLANATION}

**Findings:** $(jq '.findings | length' /tmp/review-output.json) issues found"
```

### Pattern C: Codex Cloud Automatic Reviews

If you connect the repo to Codex Cloud (codex.openai.com):

1. Enable "Code review" toggle in repo settings
2. Codex automatically posts a review on every new PR
3. Reviews respect `## Review guidelines` in AGENTS.md
4. Default severity filter: only P0 and P1 issues are posted to GitHub
5. Manual trigger: comment `@codex review` on any PR

This is the lowest-effort option but requires Codex Cloud access and sends code to OpenAI's cloud.

---

## 7. AGENTS.md for the Dual-Agent Setup

### Recommended Structure

For a project where Claude Code writes code and Codex reviews PRs, the AGENTS.md should contain shared architectural knowledge that both agents need:

```markdown
# AGENTS.md

## Project architecture

This is a Python/FastAPI + React/TypeScript monorepo using Domain-Driven Design.

### Bounded contexts (DO NOT cross-import)

| Context   | Directory        | Owns                                    |
|-----------|------------------|-----------------------------------------|
| Board     | `src/board/`     | Projects, Epics, Features, Tasks        |
| Agent     | `src/agent/`     | Worktrees, Sessions, registration       |
| Document  | `src/document/`  | Append-only document storage            |
| Gateway   | `src/gateway/`   | API composition, auth, SSE              |

Contexts communicate through `interfaces.py`, never by importing each other's internals.

## Review guidelines

- Cross-context imports are DDD boundary violations. Flag as priority 3.
- All API endpoints must match the OpenAPI contract in `docs/contracts/`.
- Pydantic Update schemas must include all fields that the endpoint accepts.
  `model_dump(exclude_unset=True)` silently drops unrecognized fields.
- `raise HTTPException` inside `except` blocks must use `raise ... from None`
  (ruff B904).
- Auth: agent-facing endpoints use Bearer token; dashboard endpoints are public.
- Never hardcode ports. Use environment variables.
- All model classes must be imported in `tests/conftest.py`.
- Frontend must import API types from `generated-types.ts`, never hand-write them.

## Testing requirements

- Backend tests use real PostgreSQL, no mocks.
- Frontend tests use @testing-library/react patterns.
- E2E tests create their own isolated database and servers.
- Run `make quality` before any PR.

## Tech stack

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, PostgreSQL
- Frontend: React 18, Vite, TypeScript, Vitest
- Linting: ruff, mypy
- Testing: pytest, Vitest, Playwright
```

### Why a Shared AGENTS.md Works

- **Claude Code** reads CLAUDE.md (its native format) but can be configured to also read AGENTS.md via includes or by duplicating key rules.
- **Codex CLI** reads AGENTS.md natively. Configure `project_doc_fallback_filenames = ["CLAUDE.md"]` in `.codex/config.toml` so it also picks up CLAUDE.md content.
- The `## Review guidelines` section is specifically recognized by Codex Cloud's review feature.

### Recommended File Layout

```
repo/
  CLAUDE.md              # Claude Code primary instructions (full detail)
  AGENTS.md              # Shared rules + review guidelines (Codex reads this)
  .codex/config.toml     # Codex config (fallback to CLAUDE.md)
  src/
    board/AGENTS.md      # Context-specific review rules for board
    agent/AGENTS.md      # Context-specific review rules for agent
    gateway/AGENTS.md    # Context-specific review rules for gateway
```

Per-directory AGENTS.md files let Codex apply context-specific review guidance to changed files in that directory. This is useful for DDD -- each context can have its own review rules.

---

## 8. Gotchas and Limitations

### Confirmed Limitations

1. **`codex fork` requires a TTY.** You cannot fork a session headlessly. Use `codex exec` for non-interactive work. (GitHub issue #11750)

2. **No CLI timeout flag.** Timeout is config-only (`stream_idle_timeout_ms`). For subprocess usage, set your own timeout in Python (`subprocess.run(timeout=300)`).

3. **`--output-schema` strict mode.** The JSON Schema must follow OpenAI's "strict schema" rules (similar to function calling). This means: `additionalProperties: false` on every object, all properties in `required`, no `oneOf`/`anyOf` at the top level.

4. **Line numbers in review output may be approximate.** The model reports line numbers based on its understanding of the diff. Post-processing should validate that file paths and line numbers actually exist before posting PR comments.

5. **32 KiB AGENTS.md limit.** Combined instruction content is capped. If your CLAUDE.md is large, Codex may truncate it when using fallback filenames. Keep AGENTS.md focused on review-relevant rules.

6. **Python SDK is experimental.** It requires a local checkout of the Codex repo and is not distributed as a standalone package on PyPI (the `openai-codex-sdk` on PyPI is a community wrapper, not official).

7. **Model recommendation:** OpenAI explicitly recommends `gpt-5.2-codex` for code review accuracy. Using other models may produce lower-quality reviews.

8. **Sandbox in review context.** For pure review (no file modifications), use `--sandbox read-only`. The default `--full-auto` sets `workspace-write`, which is more permissive than needed.

9. **Cost considerations.** Each review invocation is an API call to OpenAI. Large diffs will consume more tokens. Consider filtering the diff to only include relevant files before sending.

10. **Security:** When using `--full-auto` or `--yolo` in CI, the OpenAI API key is accessible to the Codex process. Use `safety-strategy: drop-sudo` in GitHub Actions to mitigate. On self-hosted runners, use environment variable filtering.

### Not Yet Determined

- **Exact token limits for diff input via stdin.** The documentation does not specify a maximum diff size. Practically, this is bounded by the model's context window.
- **Rate limits for `codex exec` in CI.** Standard OpenAI API rate limits apply, but Codex-specific quotas (if any) are not documented.

---

## 9. Summary: Recommended Implementation for cloglog

### Minimum Viable Review Bot

1. Create `AGENTS.md` at repo root with `## Review guidelines` section
2. Create `.github/codex/review-schema.json` with the structured output schema
3. Create `.github/codex/prompts/review.md` with the review prompt
4. Use either:
   - **GitHub Action** (`openai/codex-action@v1`) for zero-infra setup
   - **Webhook script** calling `codex exec` for self-hosted control
5. Post structured findings as inline PR comments via GitHub API

### Command Cheat Sheet

```bash
# Simple review, free-text output
git diff main...HEAD | codex exec --full-auto "Review this diff for bugs"

# Structured review with JSON schema
git diff main...HEAD | codex exec \
  --full-auto \
  --output-schema review-schema.json \
  -o review.json \
  --ephemeral \
  -m gpt-5.2-codex \
  "Review this code change"

# Full CI invocation (no TTY, no persistence, no sudo)
CODEX_API_KEY="$KEY" codex exec \
  --sandbox read-only \
  --output-schema review-schema.json \
  -o review.json \
  --ephemeral \
  --skip-git-repo-check \
  --color never \
  -C /workspace \
  -m gpt-5.2-codex \
  - < prompt-with-diff.md
```

---

## Sources

- [Codex CLI Reference](https://developers.openai.com/codex/cli/reference)
- [Codex Non-Interactive Mode](https://developers.openai.com/codex/noninteractive)
- [AGENTS.md Guide](https://developers.openai.com/codex/guides/agents-md)
- [Codex GitHub Action](https://developers.openai.com/codex/github-action)
- [Build Code Review with Codex SDK (Cookbook)](https://developers.openai.com/cookbook/examples/codex/build_code_review_with_codex_sdk)
- [Codex SDK Documentation](https://developers.openai.com/codex/sdk)
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced)
- [Codex GitHub Integration](https://developers.openai.com/codex/integrations/github)
- [Codex CLI GitHub Repository](https://github.com/openai/codex)
- [LLM Prompting for Security Reviews](https://crashoverride.com/blog/prompting-llm-security-reviews)
- [Meta Structured Prompting for Code Review](https://venturebeat.com/orchestration/metas-new-structured-prompting-technique-makes-llms-significantly-better-at)
