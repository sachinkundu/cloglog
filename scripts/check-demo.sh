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

# Skip if this branch only has doc/spec changes (no code to demo)
CODE_CHANGES=$(git diff main --name-only 2>/dev/null | grep -vE '^docs/|^CLAUDE\.md|^\.claude/' | head -1)
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
DEMO_DIR=""
if compgen -G "docs/demos/*/" > /dev/null 2>&1; then
  for dir in docs/demos/*/; do
    [[ -d "$dir" ]] || continue
    if echo "$dir" | grep -qi "$FEATURE"; then
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
if [[ ! -f "$DEMO_FILE" ]]; then
  echo "  ERROR: Demo directory exists but demo.md is missing: $DEMO_FILE"
  echo "  Run 'make demo' to generate the demo document."
  exit 1
fi

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
