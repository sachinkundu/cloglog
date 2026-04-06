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

# Detect feature name from DEMO_FEATURE env var or branch name
FEATURE="${DEMO_FEATURE:-}"
if [[ -z "$FEATURE" ]]; then
  # Extract feature identifier from branch name
  # Patterns: wt-frontend -> look for feature in commit, f23-impl -> f23, etc.
  case "$BRANCH" in
    f[0-9]*-*)
      # Branch like f23-impl or f23-design-spec — extract f<N> prefix
      FEATURE=$(echo "$BRANCH" | grep -oP '^f\d+' || echo "")
      ;;
    wt-*)
      # Worktree branch — check for DEMO_FEATURE in .env
      if [[ -f .env ]]; then
        FEATURE=$(grep -oP 'DEMO_FEATURE=\K.*' .env 2>/dev/null || echo "")
      fi
      ;;
  esac
fi

if [[ -z "$FEATURE" ]]; then
  echo "  Could not detect feature name. Set DEMO_FEATURE env var or use f<N>-* branch naming."
  echo "  Skipping demo check."
  exit 0
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
  # If no demo directories exist at all, the system isn't adopted yet — warn but pass
  if ! compgen -G "docs/demos/*/" > /dev/null 2>&1; then
    echo "  No demos exist yet — demo system not yet adopted. Skipping."
    exit 0
  fi
  # Other demos exist but this feature is missing one — fail
  echo "  ERROR: No demo directory found matching feature '$FEATURE' in docs/demos/"
  echo "  Expected: docs/demos/<feature-name>/demo.md"
  echo "  Run 'make demo' to generate the demo document."
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
