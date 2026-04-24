#!/bin/bash
# Quality gate check: verify demo.md exists and passes showboat verify.
# Called by `make demo-check`.
#
# Exits 0 if:
#   - On main branch (no demo required)
#   - Demo exists and verifies
# Exits non-zero if:
#   - Demo is missing
#   - Showboat verify fails

set -euo pipefail

# Detect current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Skip on main — no demo needed
if [[ "$BRANCH" == "main" || "$BRANCH" == "master" ]]; then
  exit 0
fi

# Skip if this branch only has doc/spec changes (no code to demo).
# Use merge-base so rebased branches don't show phantom diffs from
# already-merged work. Prefer origin/main over local main — local main is
# often behind origin (e.g., held by a prod worktree that only pulls on
# `make promote`), which would surface already-merged PRs as phantom
# code changes and block docs-only close-off PRs.
MERGE_BASE=$(git merge-base origin/main HEAD 2>/dev/null \
  || git merge-base main HEAD 2>/dev/null \
  || echo "main")
CODE_CHANGES=$(git diff "$MERGE_BASE" --name-only 2>/dev/null | grep -vE '^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|^tests/|^Makefile$|^plugins/[^/]+/(hooks|skills|agents|templates)/|^pyproject\.toml$|^ruff\.toml$|package-lock\.json$|\.lock$' | head -1 || true)
if [[ -z "$CODE_CHANGES" ]]; then
  echo "  Docs-only branch — no demo required."
  exit 0
fi

# Detect feature/branch identifier for demo lookup
FEATURE="${DEMO_FEATURE:-}"
if [[ -z "$FEATURE" ]]; then
  # Use the full branch name as the demo directory identifier
  FEATURE="$BRANCH"
fi

# Skip if docs/demos/ doesn't exist yet (demo system not yet set up)
if [[ ! -d "docs/demos" ]]; then
  echo "  docs/demos/ not found — demo system not yet initialized. Skipping."
  exit 0
fi

# Look for demo directory matching the feature
# Normalize slashes to hyphens so branch names like feat/foo match dirs like feat-foo
FEATURE_NORM="${FEATURE//\//-}"
DEMO_DIR=""
if compgen -G "docs/demos/*/" > /dev/null 2>&1; then
  for dir in docs/demos/*/; do
    [[ -d "$dir" ]] || continue
    if echo "$dir" | grep -qi "$FEATURE_NORM"; then
      DEMO_DIR="$dir"
      break
    fi
  done
fi

if [[ -z "$DEMO_DIR" ]]; then
  echo "  ERROR: No demo found matching '$FEATURE' in docs/demos/"
  echo "  Expected: docs/demos/<branch-or-feature>/demo.md"
  echo "  Create a demo with showboat before committing."
  exit 1
fi

DEMO_FILE="${DEMO_DIR}demo.md"
EXEMPTION_FILE="${DEMO_DIR}exemption.md"

# Acceptance path 1 — demo.md wins over exemption.md if both present.
if [[ -f "$DEMO_FILE" ]]; then
  # Verify with showboat if available
  if command -v showboat &>/dev/null || uvx showboat --version &>/dev/null 2>&1; then
    echo "  Verifying $DEMO_FILE..."
    if uvx showboat verify "$DEMO_FILE" 2>&1; then
      echo "  Demo verified successfully."
    else
      echo "  ERROR: showboat verify failed for $DEMO_FILE"
      echo "  Re-run 'make demo' to update the demo document."
      exit 1
    fi
  else
    echo "  showboat not available — skipping verification (demo.md exists)"
  fi
  exit 0
fi

# Acceptance path 2 — exemption.md with a matching diff_hash.
if [[ -f "$EXEMPTION_FILE" ]]; then
  # Extract diff_hash from the YAML frontmatter. Using grep+sed per the
  # project rule in docs/invariants.md § "Hook scripts parse config with
  # grep+sed" — no Python YAML dependency, and anchoring to the first
  # `---` block avoids picking up a `diff_hash:` line that happens to
  # appear in the prose body.
  STORED_HASH=$(awk '
    /^---[[:space:]]*$/ { fence++; next }
    fence == 1 && /^diff_hash:[[:space:]]+/ {
      sub(/^diff_hash:[[:space:]]+/, "")
      gsub(/[[:space:]]+$/, "")
      print
      exit
    }
  ' "$EXEMPTION_FILE")

  if [[ -z "$STORED_HASH" ]]; then
    echo "  ERROR: $EXEMPTION_FILE is missing a diff_hash in its frontmatter."
    echo "  Re-run the 'cloglog:demo' skill to regenerate the exemption."
    exit 1
  fi

  # Hash MUST be computed with the same command the classifier uses so
  # bytes match exactly. The classifier emits sha256 of
  # `git diff origin/main...HEAD`; because MERGE_BASE is already the
  # resolved merge-base of origin/main and HEAD, `git diff $MERGE_BASE HEAD`
  # is bit-identical to the three-dot form.
  CURRENT_HASH=$(git diff "$MERGE_BASE" HEAD 2>/dev/null | sha256sum | awk '{print $1}')

  if [[ "$STORED_HASH" == "$CURRENT_HASH" ]]; then
    echo "  Exemption verified (diff_hash matches): $EXEMPTION_FILE"
    exit 0
  fi

  echo "  ERROR: exemption is stale for current diff — re-run 'cloglog:demo' skill to reclassify."
  echo "    stored  diff_hash: $STORED_HASH"
  echo "    current diff_hash: $CURRENT_HASH"
  exit 1
fi

# Neither demo.md nor exemption.md exists — real failure.
echo "  ERROR: Demo directory exists but neither demo.md nor exemption.md is present: $DEMO_DIR"
echo "  Run 'make demo' (or the 'cloglog:demo' skill) to generate one."
exit 1
