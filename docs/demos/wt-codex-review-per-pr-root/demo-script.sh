#!/usr/bin/env bash
# Demo for T-278: codex now reviews the PR's owning worktree, not prod's
# stale main checkout. Per-PR project_root resolution with a shared-host
# filesystem invariant; gateway routes through an Agent-context OHS so the
# Gateway-owns-no-tables boundary stays clean.
#
# Verify-safe: no pytest, no DB, no subprocess against ollama. Every
# ``exec`` block is either a filesystem boolean or an in-process python
# proof that prints only deterministic OK/FAIL lines.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

# showboat init refuses to overwrite — delete first so ``make demo`` is re-runnable.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Codex now reviews the PR's owning worktree, not prod's stale main. T-278 resolves project_root per PR via an Agent Open Host Service; the old host-level fallback (T-255) remains for PRs whose worktree is not on this host."

# ===================================================================
uvx showboat note "$DEMO_FILE" "### T-278 acceptance evidence — file-level booleans

Every T-278 acceptance item reduces to a file-level change (new helper,
new Protocol, new repository method, new OHS factory) or a regression
guard (DDD boundary pin). The exec blocks below prove each one as a
boolean without touching a live service — safe under \`showboat verify\`."

# ----- Gateway helper exists -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/gateway/review_engine.py
   grep -q "^async def resolve_pr_review_root" "$F" && echo "resolve_pr_review_root_defined=yes" || echo "resolve_pr_review_root_defined=MISSING"
   grep -q "def resolve_review_source_root" "$F" && echo "host_level_resolver_preserved=yes" || echo "host_level_resolver_preserved=MISSING"'

# ----- Agent context exposes IWorktreeQuery Protocol + WorktreeRow DTO -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/agent/interfaces.py
   grep -q "class IWorktreeQuery" "$F" && echo "IWorktreeQuery_protocol_defined=yes" || echo "IWorktreeQuery_protocol_defined=MISSING"
   grep -q "class WorktreeRow" "$F" && echo "WorktreeRow_dto_defined=yes" || echo "WorktreeRow_dto_defined=MISSING"
   grep -q "async def find_by_branch" "$F" && echo "find_by_branch_protocol_method=yes" || echo "find_by_branch_protocol_method=MISSING"'

# ----- OHS factory in Agent services -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/agent/services.py
   grep -q "^def make_worktree_query" "$F" && echo "make_worktree_query_factory=yes" || echo "make_worktree_query_factory=MISSING"'

# ----- New repository method (any-status lookup) -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/agent/repository.py
   grep -q "async def find_worktree_by_branch_any_status" "$F" && echo "repository_method=yes" || echo "repository_method=MISSING"'

# ----- Call-site update in _review_pr uses resolve_pr_review_root -----
uvx showboat exec "$DEMO_FILE" bash \
  'F=src/gateway/review_engine.py
   grep -q "project_root = await resolve_pr_review_root" "$F" && echo "call_site_uses_per_pr_resolver=yes" || echo "call_site_uses_per_pr_resolver=MISSING"'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### DDD boundary — Gateway must NOT import Agent models or repository

Per \`docs/ddd-context-map.md\` (Gateway owns no tables) and the PR #187
round 2 CRITICAL precedent, Gateway consumes Agent only through the
Protocol + factory. The two grep invocations below assert **absence**
(non-zero exit) — catching both top-level and lazy imports. CLAUDE.md
\"Leak-after-fix\" rule: asserting absence beats asserting presence."

uvx showboat exec "$DEMO_FILE" bash \
  'F=src/gateway/review_engine.py
   if grep -qE "^from src\.agent\.(models|repository)" "$F"; then
     echo "top_level_agent_models_or_repository_import=PRESENT_FAIL"
   else
     echo "top_level_agent_models_or_repository_import=absent_ok"
   fi
   if grep -qE "from src\.agent\.(models|repository)" "$F"; then
     echo "any_indent_agent_models_or_repository_import=PRESENT_FAIL"
   else
     echo "any_indent_agent_models_or_repository_import=absent_ok"
   fi'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### In-process behaviour proofs

\`docs/demos/wt-codex-review-per-pr-root/proof.py\` wires a stub
\`IWorktreeQuery\`, a synthetic \`WebhookEvent\`, and a tmp git repo (for
the drift case) to exercise \`resolve_pr_review_root\` without any DB,
webhook, or codex subprocess. Each mode prints only boolean OK/FAIL
lines — no SHAs, no timestamps — so \`showboat verify\` stays byte-exact."

# ----- Happy path — worktree row + on-disk path -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-codex-review-per-pr-root/proof.py happy'

# ----- Fallback — no worktree row → settings.review_source_root -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-codex-review-per-pr-root/proof.py fallback'

# ----- Drift — worktree HEAD != event head_sha → worktree still wins, warn -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-codex-review-per-pr-root/proof.py drift'

# ===================================================================
uvx showboat note "$DEMO_FILE" "### Spec updated

\`docs/design/two-stage-pr-review.md\` §9 documents the per-PR review-
root rule as authoritative; future readers find the answer in the spec,
not by spelunking git."

uvx showboat exec "$DEMO_FILE" bash \
  'F=docs/design/two-stage-pr-review.md
   grep -q "## 9. Per-PR review root resolution" "$F" && echo "spec_section_9_present=yes" || echo "spec_section_9_present=MISSING"
   grep -q "T-278" "$F" && echo "spec_cites_T-278=yes" || echo "spec_cites_T-278=MISSING"
   grep -q "T-255" "$F" && echo "spec_cites_T-255=yes" || echo "spec_cites_T-255=MISSING"'
