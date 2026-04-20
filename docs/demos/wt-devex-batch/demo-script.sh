#!/usr/bin/env bash
# Demo: three plugin/script-level devex fixes — T-250, T-251, T-252.
# Deterministic evidence only (greps + fixed strings). No servers needed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

# Normalize slashes in branch names — scripts/check-demo.sh maps feat/foo → feat-foo.
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

uvx showboat init "$DEMO_FILE" \
  "Worktree bootstrap installs the dev toolchain, demo-script templates survive slash-named branches, and devex guidance correctly reflects that mcp-server/dist/ is gitignored."

# ────────────────────────────── T-250 ──────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "T-250: .cloglog/on-worktree-create.sh now runs 'uv sync --extra dev' + sanity-checks pytest, so fresh worktree venvs ship with the dev toolchain."

uvx showboat exec "$DEMO_FILE" bash \
  "grep -n 'uv sync --extra dev\\|pytest not in' .cloglog/on-worktree-create.sh"

# ────────────────────────────── T-251 ──────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "T-251: both halves of the demo workflow now normalize slash-named branches via \${BRANCH//\\//-}, matching scripts/check-demo.sh. (a) plugins/cloglog/skills/demo/SKILL.md templates produce docs/demos/feat-foo/ paths, (b) scripts/run-demo.sh uses FEATURE_NORM for its directory lookup so 'make demo' actually finds the written path."

uvx showboat exec "$DEMO_FILE" bash \
  "printf 'skill_md_normalized_hits=%s\nskill_md_raw_hits=%s\nrun_demo_uses_feature_norm=%s\n' \"\$(grep -cE 'BRANCH//\\\\/' plugins/cloglog/skills/demo/SKILL.md)\" \"\$(grep -cE 'docs/demos/\\\$\\(git rev-parse' plugins/cloglog/skills/demo/SKILL.md)\" \"\$(grep -c 'FEATURE_NORM' scripts/run-demo.sh)\""

# ────────────────────────────── T-252 ──────────────────────────────
uvx showboat note "$DEMO_FILE" \
  "T-252: no live template carried the 'they are checked in' phrasing — the misstatement existed only in a work-log. CLAUDE.md now documents durably that mcp-server/dist/ is gitignored, never committed, and must be rebuilt locally with 'cd mcp-server && make build' when mcp-server/src/ changes (neither on-worktree-create.sh nor CI rebuilds it)."

uvx showboat exec "$DEMO_FILE" bash \
  "printf 'stale_phrase_in_live_templates=%s\nnew_guidance_in_claude_md=%s\n' \"\$(grep -l 'they are checked in' plugins/cloglog/skills/*/SKILL.md CLAUDE.md 2>/dev/null | wc -l)\" \"\$(grep -c 'mcp-server/dist.*gitignored' CLAUDE.md)\""

uvx showboat verify "$DEMO_FILE"
