#!/usr/bin/env bash
# Demo: T-255 — review engine's project_root resolves from settings.review_source_root,
# not Path.cwd(). Eliminates false-negatives from codex reading the prod checkout
# when that checkout trails main.
#
# Called by `make demo`. No server interaction — this is a config-level fix,
# proven by grep + a Settings load under two environments.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BRANCH_DIR="${BRANCH//\//-}"
DEMO_FILE="docs/demos/$BRANCH_DIR/demo.md"

uvx showboat init "$DEMO_FILE" \
  "The PR reviewer now reads source files from a configured main checkout instead of Path.cwd(). False-negatives where codex couldn't see code already merged to main (because the backend runs out of a prod checkout that trails main) are eliminated."

# --- Background ------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Bug scenario (observed on PR #158): backend process runs out of \
/home/sachin/code/cloglog-prod/, which is a git worktree that only advances \
on \`make promote\`. The review engine passed \`-C \$(cwd)\` to codex, so \
codex's filesystem view was the prod checkout. When a PR referenced code \
merged to main but not yet promoted, codex flagged it as missing. Reviewers \
learn to dismiss codex → genuine issues hide in the noise."

uvx showboat note "$DEMO_FILE" \
  "Fix: new Settings field \`review_source_root: Path | None\` (env \
REVIEW_SOURCE_ROOT). When set, the review engine passes that path to codex's \
\`-C\` flag and uses it as the subprocess cwd. Unset → falls back to \
Path.cwd() (fine for dev). Prod must export REVIEW_SOURCE_ROOT pointing at \
the main checkout."

# --- Proof 1: config field exists ------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 1 — Settings carries the new field with the right type and default."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "review_source_root: Path | None" src/shared/config.py'

# --- Proof 2: review engine reads from setting, not cwd directly -----------

uvx showboat note "$DEMO_FILE" \
  "Proof 2 — review_engine._run_review_agent now resolves project_root via \
the setting, with Path.cwd() only as a fallback when unset."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -c "settings.review_source_root or Path.cwd()" src/gateway/review_engine.py'

# --- Proof 3: naked cwd assignment is gone ---------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 3 — the buggy \`project_root = Path.cwd()\` assignment (no setting \
fallback) is gone. If a future refactor reintroduces it, this proof flips \
from 'fixed' to 'bug remains'."

uvx showboat exec "$DEMO_FILE" bash \
  'if grep -qE "^        project_root = Path\.cwd\(\)$" src/gateway/review_engine.py; then echo "bug remains"; else echo "fixed"; fi'

# --- Proof 4: Settings picks up env var (default branch) -------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 4a — with REVIEW_SOURCE_ROOT unset, Settings.review_source_root is \
None and the engine falls back to Path.cwd()."

uvx showboat exec "$DEMO_FILE" bash \
  'env -u REVIEW_SOURCE_ROOT uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"review_source_root:\", s.review_source_root)"'

# --- Proof 5: Settings picks up env var (override branch) ------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 4b — with REVIEW_SOURCE_ROOT set, Settings picks it up as a Path \
and the engine will pass that value to codex -C."

uvx showboat exec "$DEMO_FILE" bash \
  'REVIEW_SOURCE_ROOT=/home/sachin/code/cloglog uv run --no-sync python -c "from src.shared.config import Settings; s = Settings(_env_file=None); print(\"review_source_root:\", s.review_source_root)"'

# --- Proof 6: startup log helper exists ------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 5 — new helper \`log_review_source_root\` is wired into app.py's \
lifespan so the backend logs the resolved path and HEAD SHA at boot. A \
stale prod checkout becomes visible in the log, not just in false-negative \
reviews."

uvx showboat exec "$DEMO_FILE" bash \
  'grep -l log_review_source_root src/gateway/app.py src/gateway/review_engine.py | wc -l'

# --- Proof 7: tests pass ---------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "Proof 6 — new TestReviewSourceRoot class covers both branches (setting \
set / None), the regression guard that -C is always passed, and the \
startup-log probe against a bogus path and a real git dir. 7 new tests, all \
pass; the full review-engine file still passes 71 tests end-to-end."

uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/gateway/test_review_engine.py -k TestReviewSourceRoot -q --no-header 2>&1 | grep -oE "[0-9]+ passed"'

uvx showboat exec "$DEMO_FILE" bash \
  'uv run pytest tests/gateway/test_review_engine.py -q --no-header 2>&1 | grep -oE "[0-9]+ passed"'

uvx showboat verify "$DEMO_FILE"
