#!/bin/bash
# Enforce quality gate: make quality must pass before git commit/push/PR.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Only validate Bash tool calls
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

# Check if this is a commit, push, or PR command
if ! echo "$COMMAND" | grep -qE '(git commit|git push|gh pr create)'; then
  exit 0
fi

# Run quality checks
cd "$CWD" || exit 0

if ! make quality > /tmp/quality-check-$$.log 2>&1; then
  echo "Blocked: 'make quality' failed. Fix issues before committing." >&2
  echo "---" >&2
  tail -20 /tmp/quality-check-$$.log >&2
  rm -f /tmp/quality-check-$$.log
  exit 2
fi

rm -f /tmp/quality-check-$$.log

# Demo check and e2e tests — only required on push and PR creation, not on every commit
if echo "$COMMAND" | grep -qE '(git push|gh pr create)'; then
  # Demo check temporarily skipped
  # if ! make demo-check > /tmp/demo-check-$$.log 2>&1; then
  #   echo "Blocked: demo check failed. Create a demo before pushing/creating PR." >&2
  #   echo "---" >&2
  #   tail -10 /tmp/demo-check-$$.log >&2
  #   rm -f /tmp/demo-check-$$.log
  #   exit 2
  # fi
  # rm -f /tmp/demo-check-$$.log

  # Playwright e2e tests — run if playwright dir exists and has tests
  if [[ -f "tests/e2e/playwright/package.json" ]]; then
    echo "Running Playwright e2e tests..." >&2
    if ! (cd tests/e2e/playwright && npx playwright test --reporter=list) > /tmp/e2e-check-$$.log 2>&1; then
      echo "Blocked: Playwright e2e tests failed. Fix before pushing." >&2
      echo "---" >&2
      tail -20 /tmp/e2e-check-$$.log >&2
      rm -f /tmp/e2e-check-$$.log
      exit 2
    fi
    rm -f /tmp/e2e-check-$$.log
  fi
fi

exit 0
