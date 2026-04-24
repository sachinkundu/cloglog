#!/usr/bin/env bash
# Demo for T-281: per-PR review root resolver follows the tasks.pr_url
# chain (Path 0) and materializes a disposable git-worktree checkout
# when the candidate's HEAD disagrees with event.head_sha (SHA-check
# temp-dir fallback). Resolves the main-agent close-out PR miss that
# caused false-positive findings on PR #200 / PR #202.
#
# Verify-safe: no pytest, no DB, no network.  Every exec block is either
# a file-level grep boolean or an in-process python3 proof whose output
# is a deterministic key=value set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DEMO_DIR="docs/demos/${BRANCH//\//-}"
DEMO_FILE="$DEMO_DIR/demo.md"

rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "Codex now reviews main-agent close-out PRs against the PR's actual commit — no more false-positive findings from reading prod's stale main tree."

# ==================================================================
uvx showboat note "$DEMO_FILE" "### Scope evidence — file-level booleans

Every T-281 scope item maps to a named symbol added in a specific file.
The booleans below prove each one landed where the task description
said it would."

# ----- Path 0: IWorktreeQuery.find_by_pr_url Protocol method -----
uvx showboat exec "$DEMO_FILE" bash \
  'I=src/agent/interfaces.py
   grep -q "async def find_by_pr_url" "$I" && echo "interfaces_find_by_pr_url=yes" || echo "interfaces_find_by_pr_url=MISSING"
   grep -q "WorktreeRow | None" "$I" && echo "interfaces_returns_worktreerow=yes" || echo "interfaces_returns_worktreerow=MISSING"'

# ----- Path 0: adapter implementation composes Board + Agent repos -----
uvx showboat exec "$DEMO_FILE" bash \
  'S=src/agent/services.py
   grep -q "async def find_by_pr_url" "$S" && echo "services_find_by_pr_url=yes" || echo "services_find_by_pr_url=MISSING"
   grep -q "find_task_by_pr_url_for_project" "$S" && echo "services_uses_project_scoped_join=yes" || echo "services_uses_project_scoped_join=MISSING"
   grep -q "BoardRepository(session)" "$S" && echo "factory_wires_board_repo=yes" || echo "factory_wires_board_repo=MISSING"'

# ----- PrReviewRoot dataclass + is_temp/main_clone fields -----
uvx showboat exec "$DEMO_FILE" bash \
  'R=src/gateway/review_engine.py
   grep -q "class PrReviewRoot" "$R" && echo "dataclass_defined=yes" || echo "dataclass_defined=MISSING"
   grep -q "is_temp: bool = False" "$R" && echo "is_temp_field=yes" || echo "is_temp_field=MISSING"
   grep -q "main_clone: Path | None" "$R" && echo "main_clone_field=yes" || echo "main_clone_field=MISSING"'

# ----- SHA-check + temp-dir helpers -----
uvx showboat exec "$DEMO_FILE" bash \
  'R=src/gateway/review_engine.py
   grep -q "async def _create_review_checkout" "$R" && echo "create_helper=yes" || echo "create_helper=MISSING"
   grep -q "async def _remove_review_checkout" "$R" && echo "remove_helper=yes" || echo "remove_helper=MISSING"
   grep -q "review-checkouts" "$R" && echo "temp_dir_path_anchor=yes" || echo "temp_dir_path_anchor=MISSING"'

# ----- _review_pr uses try/finally for cleanup -----
uvx showboat exec "$DEMO_FILE" bash \
  'R=src/gateway/review_engine.py
   grep -q "review_root = await resolve_pr_review_root" "$R" && echo "caller_uses_pr_review_root=yes" || echo "caller_uses_pr_review_root=MISSING"
   grep -q "if review_root.is_temp and review_root.main_clone is not None" "$R" && echo "caller_finally_cleanup=yes" || echo "caller_finally_cleanup=MISSING"'

# ----- DDD boundary preserved — Gateway still imports only OHS names -----
uvx showboat exec "$DEMO_FILE" bash \
  'R=src/gateway/review_engine.py
   grep -q "from src.agent.models" "$R" && echo "ddd_violation_models=LEAK" || echo "ddd_violation_models=none"
   grep -q "from src.agent.repository" "$R" && echo "ddd_violation_repository=LEAK" || echo "ddd_violation_repository=none"
   grep -c "make_worktree_query" "$R"'

# ----- Design doc §9 updated -----
uvx showboat exec "$DEMO_FILE" bash \
  'D=docs/design/two-stage-pr-review.md
   grep -q "T-281" "$D" && echo "spec_references_t281=yes" || echo "spec_references_t281=MISSING"
   grep -q "Path 0" "$D" && echo "spec_mentions_path_0=yes" || echo "spec_mentions_path_0=MISSING"
   grep -q "SHA-check + temp-dir" "$D" && echo "spec_mentions_sha_check=yes" || echo "spec_mentions_sha_check=MISSING"'

# ==================================================================
uvx showboat note "$DEMO_FILE" "### Behaviour proof — in-process resolver runs

Three standalone Python proofs exercise the real resolver + \`_review_pr\`
code paths with stubbed worktree queries and mocked git helpers.  No
pytest, no DB — \`python3 proof_*.py\` runs them directly.  The three
printed key=value blocks below are the exact bytes \`showboat verify\`
re-compares against."

# ----- Path 0 hit for main-agent close-out PR shape -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-t281-resolver-path0/proof_path0.py'

# ----- SHA mismatch routes to temp-dir checkout -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-t281-resolver-path0/proof_sha_mismatch.py'

# ----- Cleanup fires even when reviewer crashes -----
uvx showboat exec "$DEMO_FILE" bash \
  'uv run python docs/demos/wt-t281-resolver-path0/proof_cleanup.py'

uvx showboat verify "$DEMO_FILE"
